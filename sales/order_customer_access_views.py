from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from sales.access.views import root_required
from sales.models import OrderAccountProfile, OrderCustomerAccessGrant, OrderEvent, SalesOrder
from sales.services.order_customer_access import set_customer_access


class AccountChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.user.get_full_name() or obj.user.username} (@{obj.user.username})／{obj.source or '未設定車行'}"


class GrantForm(forms.Form):
    account = AccountChoice(label="合作車行人員帳號", queryset=OrderAccountProfile.objects.none())
    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    expected_identity_epoch = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    can_view = forms.BooleanField(label="查看本筆訂單（客戶版）", required=False)
    can_print = forms.BooleanField(label="列印本筆訂購單及個資同意書", required=False)
    reason = forms.CharField(label="授權／撤銷原因", max_length=500, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, accounts, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = accounts
        self.fields["reason"].widget.attrs["class"] = "form-control"


@root_required
@require_http_methods(["GET", "POST"])
def order_customer_access(request, pk):
    order = get_object_or_404(SalesOrder, pk=pk)
    grants = OrderCustomerAccessGrant.objects.filter(order=order).select_related("account__user", "account__source", "changed_by").order_by("account__user__username")
    accounts = OrderAccountProfile.objects.filter(
        Q(kind="dealer", user__is_active=True, source__active=True) | Q(pk__in=grants.values("account_id"))
    ).select_related("user", "source").order_by("source__name", "user__username")
    selected = request.POST.get("account") if request.method == "POST" else request.GET.get("account")
    account = get_object_or_404(accounts, pk=selected) if selected and str(selected).isdigit() else None
    grant = grants.filter(account=account).first() if account else None
    initial = {"account": account, "expected_revision": grant.revision if grant else 0,
               "expected_identity_epoch": account.identity_epoch if account else 0,
               "can_view": grant.can_view if grant else True, "can_print": grant.can_print if grant else False}
    form = GrantForm(request.POST or None, accounts=accounts, initial=initial)
    if request.method == "POST" and form.is_valid():
        if request.POST.get("action") not in {"save", "revoke"}:
            form.add_error(None, "請選擇儲存或撤銷授權。")
        else:
            data = form.cleaned_data
            try:
                set_customer_access(actor=request.user, order_id=pk, account_id=data["account"].pk,
                    expected_revision=data["expected_revision"], expected_identity_epoch=data["expected_identity_epoch"],
                    can_view=data["can_view"], can_print=data["can_print"], active=request.POST["action"] == "save", reason=data["reason"])
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, "單筆額外授權已更新；訂單來源、公司抬頭及帳務保持不變。")
                return redirect(f"{reverse('order_customer_access', args=[pk])}?account={data['account'].pk}")
    return render(request, "sales/order_customer_access.html", {"order": order, "form": form,
        "accounts": accounts, "selected_account": account, "grants": grants,
        "audit_events": OrderEvent.objects.filter(order=order, event_type="customer_access_updated").order_by("-pk")[:20]})
