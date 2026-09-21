from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_http_methods

from sales.access.views import root_required
from sales.models import OrderAccountProfile, OrderIntakeAttachment, SalesOrder, SalesSource, UserAccountAuditLog
from sales.services.order_intake import is_dealer, receive_order, scoped_orders, scoped_drafts


@login_required
@require_http_methods(["GET", "HEAD"])
def intake_drafts(request):
    from django.core.paginator import Paginator
    from sales.access.services import AccessPolicy
    if not AccessPolicy(request.user).screen("order_intake", "operate"):
        raise PermissionDenied("沒有建立訂單權限。")
    rows = scoped_drafts(request.user, reception=True).filter(data___reception=True).order_by("-updated_at", "pk")
    return render(request, "sales/intake_drafts.html", {"page_obj": Paginator(rows, 20).get_page(request.GET.get("page"))})


@login_required
@require_POST
def order_receive(request, pk):
    get_object_or_404(SalesOrder, pk=pk)
    try:
        order = receive_order(request.user, pk)
    except ValidationError as exc:
        messages.warning(request, " ".join(exc.messages))
    else:
        messages.success(request, f"已接單：{order.number}，由你負責後續處理。")
    return redirect("order_detail", pk=pk)


class AccountScopeForm(forms.ModelForm):
    expected_revision = forms.IntegerField(widget=forms.HiddenInput, min_value=0)

    class Meta:
        model = OrderAccountProfile
        fields = ["kind", "source", "order_scope"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["source"].queryset = SalesSource.objects.filter(active=True).order_by("source_type", "name")
        self.fields["expected_revision"].initial = self.instance.revision
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


@root_required
@require_http_methods(["GET", "POST"])
def order_account_scope(request, pk):
    account = get_object_or_404(get_user_model(), pk=pk)
    profile = OrderAccountProfile.objects.filter(user=account).first() or OrderAccountProfile(user=account, order_scope="all")
    form = AccountScopeForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=account.pk)
            current = OrderAccountProfile.objects.select_for_update().filter(user=account).first()
            if form.cleaned_data["expected_revision"] != (current.revision if current else 0):
                form.add_error(None, "設定已被其他視窗更新，請重新整理。")
            else:
                changed = form.save(commit=False)
                changed.revision += 1
                changed.save()
                UserAccountAuditLog.objects.create(actor=request.user, target=account, target_username=account.username, action="update", description="修改下單身分與訂單資料範圍", metadata={"before": {"kind": current.kind, "source": current.source_id, "order_scope": current.order_scope} if current else None, "after": {"kind": changed.kind, "source": changed.source_id, "order_scope": changed.order_scope}})
                messages.success(request, "下單身分與所屬通路已更新；不改變其他帳號。")
                return redirect("user_management")
    return render(request, "sales/order_account_scope.html", {"form": form, "account": account})


@login_required
@require_http_methods(["GET", "HEAD"])
def order_intake_attachment(request, pk):
    attachment = get_object_or_404(OrderIntakeAttachment, pk=pk)
    if is_dealer(request.user) and attachment.kind not in {"installment", "supplement"}:
        raise PermissionDenied("車行帳號不開放補助附件。")
    if attachment.order_id:
        from sales.access.services import policy_for
        if not policy_for(request).route("order_detail"):
            raise PermissionDenied
        get_object_or_404(scoped_orders(request.user), pk=attachment.order_id)
    else:
        get_object_or_404(scoped_drafts(request.user), pk=attachment.draft_id)
    try:
        stream = attachment.file.open("rb")
    except FileNotFoundError:
        raise Http404("附件檔案不存在，請聯絡店內人員。") from None
    from pathlib import Path
    preview = request.GET.get("preview") == "1" and Path(attachment.name).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
    response = FileResponse(stream, as_attachment=not preview, filename=attachment.name)
    if preview and response.get("Content-Type", "").split(";", 1)[0] == "application/pdf":
        response["X-Frame-Options"] = "SAMEORIGIN"
        response["Content-Security-Policy"] = "frame-ancestors 'self'"
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@require_http_methods(["GET", "HEAD"])
def order_submitted(request, pk):
    """接待確認只讀本人建立的本筆摘要，不載入內部財務明細。"""
    order = get_object_or_404(scoped_orders(request.user).select_related("vehicle_model", "color"),
                              pk=pk, submitted_by=request.user)
    return render(request, "sales/order_submitted.html", {"order": order, "reception_mode": True})
