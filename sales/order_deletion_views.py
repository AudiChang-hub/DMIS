from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from sales.models import SalesOrder
from sales.services.order_deletion import change_deletion, deletion_blockers, require_access


class DeletionForm(forms.Form):
    reason = forms.CharField(label="操作原因", max_length=500, widget=forms.Textarea(attrs={"rows": 3}))
    confirmed = forms.BooleanField(label="我已確認訂單與影響，確定執行此操作")
    expected_updated_at = forms.CharField(widget=forms.HiddenInput)


@login_required
@require_http_methods(["GET", "HEAD"])
def order_recycle_bin(request):
    require_access(request.user, "view")
    rows = SalesOrder.all_objects.filter(deleted_at__isnull=False).select_related("vehicle_model", "color").order_by("-deleted_at", "-pk")
    query = request.GET.get("q", "").strip()[:160]
    if query:
        rows = rows.filter(Q(number__icontains=query) | Q(owner_name__icontains=query))
    page = Paginator(rows, 25).get_page(request.GET.get("page"))
    return render(request, "sales/order_recycle_bin.html", {"page_obj": page, "query": query})


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def order_delete(request, pk, *, restore=False):
    require_access(request.user)
    order = get_object_or_404(SalesOrder.all_objects.filter(deleted_at__isnull=not restore), pk=pk)
    form = DeletionForm(request.POST if request.method == "POST" else None,
        initial={"expected_updated_at": order.updated_at.isoformat()})
    blockers = [] if restore else deletion_blockers(order)
    if request.method == "POST" and form.is_valid():
        try:
            change_deletion(user=request.user, order_id=pk, restore=restore,
                reason=form.cleaned_data["reason"], expected_updated_at=form.cleaned_data["expected_updated_at"],
                editing_session=request.session.session_key or "")
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"訂單 {order.number} 已{'還原' if restore else '移至已刪除訂單，可由授權人員還原'}。")
            return redirect("order_recycle_bin" if restore else "order_list")
    return render(request, "sales/order_deletion_confirm.html", {"order": order, "form": form, "restore": restore, "blockers": blockers})


def order_restore(request, pk):
    return order_delete(request, pk, restore=True)
