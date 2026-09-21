from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from sales.models import SalesOrder
from sales.services.order_deletion import change_deletion, deletion_blockers, require_access, review_deletion, confirmation_token
from sales.access.services import is_root
from sales.services.order_intake import scoped_orders
from django.core.exceptions import PermissionDenied


class DeletionForm(forms.Form):
    reason = forms.CharField(label="操作原因", max_length=500, widget=forms.Textarea(attrs={"rows": 3}))
    confirmed = forms.BooleanField(label="我已確認訂單與影響，確定執行此操作")
    expected_updated_at = forms.CharField(widget=forms.HiddenInput)
    force = forms.BooleanField(label="我確認作廢此訂單的影響，不移轉到新單；刪除不代表已退款或已退車。", required=False)
    impact_confirmation = forms.CharField(required=False, widget=forms.HiddenInput)


@login_required
@require_http_methods(["GET", "HEAD"])
def order_recycle_bin(request):
    require_access(request.user, "view")
    rows = scoped_orders(request.user, SalesOrder.all_objects.filter(deleted_at__isnull=False)).select_related("vehicle_model", "color").order_by("-deleted_at", "-pk")
    query = request.GET.get("q", "").strip()[:160]
    if query:
        rows = rows.filter(Q(number__icontains=query) | Q(owner_name__icontains=query))
    page = Paginator(rows, 25).get_page(request.GET.get("page"))
    return render(request, "sales/order_recycle_bin.html", {"page_obj": page, "query": query})


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def order_delete(request, pk, *, restore=False):
    require_access(request.user)
    order = get_object_or_404(scoped_orders(request.user, SalesOrder.all_objects.filter(deleted_at__isnull=not restore)), pk=pk)
    form = DeletionForm(request.POST if request.method == "POST" else None,
        initial={"expected_updated_at": order.updated_at.isoformat(), "impact_confirmation": confirmation_token(order, request.user),
                 "reason": order.deletion_request_reason})
    root = is_root(request.user)
    form.fields["force"].required = bool(root and not restore and deletion_blockers(order) and request.POST.get("action", "delete") == "delete")
    impacts = []
    if not restore:
        if order.allocated_vehicle_id:
            impacts.append("解除本單配車；已領牌或交付的車輛停用待核對，不視為已退回新車庫存。")
        if order.registration_date or order.registration_completed_at or order.final_plate_number:
            impacts.append("領牌資料作歷史留存，退出有效訂單統計；不撤銷實際領牌。")
        if order.status == SalesOrder.Status.COMPLETED or order.delivered_at:
            impacts.append("已完成／已交付訂單：只有 admin 可確認刪除。")
        if order.payment_records.exists() or order.deposit_amount:
            impacts.append("退出有效收款待辦及營運統計，保留收款證據；不自動標記退款。")
        if order.dealer_volume_bonus_allocations.exists():
            impacts.append("作廢原單獎金分配並更新結算台數與合計；其他訂單分配不轉嫁、不改寫。")
    blockers = []
    if request.method == "POST" and form.is_valid():
        try:
            action = request.POST.get("action", "delete" if root or restore else "request")
            if action in {"request", "cancel", "reject"} and not restore:
                review_deletion(user=request.user, order_id=pk, action=action, reason=form.cleaned_data["reason"],
                    expected_updated_at=form.cleaned_data["expected_updated_at"])
            elif action == "delete" and (root or restore):
                change_deletion(user=request.user, order_id=pk, restore=restore,
                    reason=form.cleaned_data["reason"], expected_updated_at=form.cleaned_data["expected_updated_at"],
                    editing_session=request.session.session_key or "", force=form.cleaned_data["force"] and not restore,
                    confirmation=form.cleaned_data["impact_confirmation"])
            else:
                raise PermissionDenied("只有 admin 可以確認刪除。")
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            label = {"request": "提出刪除申請，等待 admin 確認", "cancel": "取消刪除申請", "reject": "駁回刪除申請"}.get(action, "還原" if restore else "移至已刪除訂單")
            messages.success(request, f"訂單 {order.number} 已{label}。")
            return redirect("order_recycle_bin" if restore else "order_list")
    return render(request, "sales/order_deletion_confirm.html", {"order": order, "form": form, "restore": restore,
        "blockers": blockers, "impacts": impacts, "deletion_admin": root,
        "expected_order_version": order.updated_at.isoformat(),
        "can_cancel_deletion": order.deletion_requested_by_id == request.user.pk})


@login_required
@require_http_methods(["GET", "HEAD"])
def order_deletion_queue(request):
    if not is_root(request.user):
        raise PermissionDenied("只有 admin 可以審核刪除。")
    rows = SalesOrder.objects.filter(deletion_requested_at__isnull=False).select_related("deletion_requested_by").order_by("deletion_requested_at", "pk")
    return render(request, "sales/order_deletion_queue.html", {"page_obj": Paginator(rows, 25).get_page(request.GET.get("page"))})


def order_restore(request, pk):
    return order_delete(request, pk, restore=True)
