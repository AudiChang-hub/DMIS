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
        fields = ["kind", "source"]

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
    profile = OrderAccountProfile.objects.filter(user=account).first() or OrderAccountProfile(user=account)
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
                UserAccountAuditLog.objects.create(actor=request.user, target=account, target_username=account.username, action="update", description="修改下單身分與所屬通路", metadata={"before": {"kind": current.kind, "source": current.source_id} if current else None, "after": {"kind": changed.kind, "source": changed.source_id}})
                messages.success(request, "下單身分與所屬通路已更新；不改變其他帳號。")
                return redirect("user_management")
    return render(request, "sales/order_account_scope.html", {"form": form, "account": account})


@login_required
@require_http_methods(["GET", "HEAD"])
def order_intake_attachment(request, pk):
    attachment = get_object_or_404(OrderIntakeAttachment, pk=pk)
    if attachment.order_id:
        get_object_or_404(scoped_orders(request.user), pk=attachment.order_id)
    else:
        get_object_or_404(scoped_drafts(request.user), pk=attachment.draft_id)
    try:
        stream = attachment.file.open("rb")
    except FileNotFoundError:
        raise Http404("附件檔案不存在，請聯絡店內人員。") from None
    response = FileResponse(stream, as_attachment=True, filename=attachment.name)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
