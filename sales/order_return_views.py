"""訂單「交車後退車」確認頁（admin only，路由列在 ROOT_ONLY）。"""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from sales.access.services import is_root
from sales.models import OrderOperationsProfile, SalesOrder
from sales.services.order_return import (
    CONFIRM_FALLBACK, REASON_LIMIT, confirm_tail, has_subsidy, lender_disbursed, manual_refund_cap, return_after_delivery,
    return_blockers, return_impacts, return_vehicle, tail_matches,
)
from sales.services.payment_ledger import ledger_totals

MONEY_ATTRS = {"class": "form-control", "inputmode": "numeric"}


class OrderReturnForm(forms.Form):
    expected_updated_at = forms.CharField(widget=forms.HiddenInput)
    forfeited_amount = forms.IntegerField(label="沒收金額", required=False, min_value=0,
        widget=forms.NumberInput(attrs={**MONEY_ATTRS, "placeholder": "不沒收留空"}))
    forfeit_reason = forms.CharField(label="沒收原因", required=False, max_length=250,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "有沒收金額時必填"}))
    manual_refund = forms.IntegerField(label="手填應退金額", required=False, min_value=1,
        widget=forms.NumberInput(attrs={**MONEY_ATTRS, "placeholder": "依帳本計算時留空"}))
    manual_refund_reason = forms.CharField(label="手填原因", required=False, max_length=200,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "例如：Excel 收款價 85,000，已現金退還客戶"}))
    refund_method = forms.ChoiceField(label="退款方式", required=False,
        choices=(("", "請選擇"), *SalesOrder.PaymentMethod.choices), widget=forms.Select(attrs={"class": "form-control"}))
    refund_reference = forms.CharField(label="退款帳號／交易資訊", required=False, max_length=250,
        widget=forms.TextInput(attrs={"class": "form-control"}))
    refunded_on = forms.DateField(label="退款／沖回日期", widget=forms.DateInput(format="%Y-%m-%d", attrs={"class": "form-control", "type": "date"}))
    lender_clawback = forms.IntegerField(label="分期公司沖回金額", required=False, min_value=1,
        widget=forms.NumberInput(attrs=MONEY_ATTRS))
    lender_reference = forms.CharField(label="分期公司沖回資訊", required=False, max_length=120,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "例如解約文件編號"}))
    resale_price = forms.IntegerField(label="領牌車再售價", required=False, min_value=1,
        widget=forms.NumberInput(attrs={**MONEY_ATTRS, "placeholder": "例如 52000"}))
    subsidy_handled = forms.BooleanField(label="我已確認汰舊／政府補助已撤回或另行處理", required=False)
    reason = forms.CharField(label="退車原因", max_length=REASON_LIMIT, widget=forms.Textarea(attrs={
        "class": "form-control", "rows": 3, "placeholder": "例如：交車後車況爭議，客戶退車並解除分期"}))
    confirm_identifier = forms.CharField(label="輸入引擎／車身號碼末 4 碼確認", max_length=12,
        widget=forms.TextInput(attrs={"class": "form-control restore-confirm-input", "autocomplete": "off",
                                      "autocapitalize": "characters", "spellcheck": "false", "placeholder": "末 4 碼"}))

    def __init__(self, *args, order=None, vehicle=None, received=0, disbursed=0, subsidy=False, manual_cap=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.order, self.vehicle, self.received, self.manual_cap = order, vehicle, received, manual_cap
        if not received:
            self.fields.pop("forfeited_amount")
            self.fields.pop("forfeit_reason")
        if manual_cap is None:
            self.fields.pop("manual_refund")
            self.fields.pop("manual_refund_reason")
            if not received:
                self.fields.pop("refund_method")
                self.fields.pop("refund_reference")
        else:
            self.fields["manual_refund"].widget.attrs["max"] = int(manual_cap)
        if disbursed:
            self.fields["lender_clawback"].required = True
            self.fields["lender_clawback"].widget.attrs["max"] = int(disbursed)
        else:
            self.fields.pop("lender_clawback")
            self.fields.pop("lender_reference")
        if vehicle is not None:
            self.fields["resale_price"].required = True
        else:
            self.fields.pop("resale_price")
        if subsidy:
            self.fields["subsidy_handled"].required = True
        else:
            self.fields.pop("subsidy_handled")
        if confirm_tail(order, vehicle) == CONFIRM_FALLBACK:
            field = self.fields["confirm_identifier"]
            field.label, field.widget.attrs["placeholder"] = f"這台車沒有識別號碼，請輸入「{CONFIRM_FALLBACK}」", CONFIRM_FALLBACK

    def clean(self):
        data = super().clean()
        forfeited = data.get("forfeited_amount") or 0
        if forfeited and forfeited > self.received:
            self.add_error("forfeited_amount", f"沒收金額不能超過客戶已確認淨實收 {self.received:,.0f} 元。")
        if forfeited and not (data.get("forfeit_reason") or "").strip():
            self.add_error("forfeit_reason", "有沒收金額時，請填寫沒收原因。")
        manual = data.get("manual_refund")
        if manual:
            if manual > self.manual_cap:
                self.add_error("manual_refund", f"最多 {self.manual_cap:,.0f} 元（Excel 歷史收款與帳本淨實收的較大者）。")
            if not (data.get("manual_refund_reason") or "").strip():
                self.add_error("manual_refund_reason", "手填應退金額時，請填寫原因。")
            if forfeited:
                self.add_error("forfeited_amount", "手填應退金額時不另計沒收，請留空。")
        refund = manual or (self.received - forfeited)
        if "refund_method" in self.fields and refund > 0 and not data.get("refund_method"):
            self.add_error("refund_method", "有應退金額時，請選擇退款方式。")
        if data.get("confirm_identifier") and not tail_matches(self.order, self.vehicle, data["confirm_identifier"]):
            self.add_error("confirm_identifier", "號碼不符，請對照上方的引擎／車身號碼再輸入一次。")
        return data


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def order_return(request, pk):
    if not is_root(request.user):
        raise PermissionDenied("只有 admin 可以辦理交車後退車。")
    order = get_object_or_404(SalesOrder.objects.select_related("vehicle_model", "color", "source", "allocated_vehicle"), pk=pk)
    ledger = ledger_totals(order)
    profile = OrderOperationsProfile.objects.filter(order=order).first()
    vehicle = return_vehicle(order)
    received = ledger["customer"]["net"]
    disbursed = lender_disbursed(order, ledger, profile)
    subsidy = has_subsidy(order)
    blockers = return_blockers(order, ledger)
    manual_cap = manual_refund_cap(order, ledger)
    form = OrderReturnForm(request.POST if request.method == "POST" else None, order=order, vehicle=vehicle,
        received=received, disbursed=disbursed, subsidy=subsidy, manual_cap=manual_cap,
        initial={"expected_updated_at": order.updated_at.isoformat(), "refunded_on": timezone.localdate(),
                 "lender_clawback": int(disbursed) if disbursed else None})
    if request.method == "POST" and not blockers and form.is_valid():
        data = form.cleaned_data
        try:
            return_after_delivery(
                user=request.user, order_id=order.pk, reason=data["reason"], expected_updated_at=data["expected_updated_at"],
                actor_name=request.user.get_full_name() or request.user.get_username(), refunded_on=data["refunded_on"],
                forfeited_amount=data.get("forfeited_amount"), forfeit_reason=data.get("forfeit_reason", ""),
                method=data.get("refund_method", ""), reference=data.get("refund_reference", ""),
                lender_clawback=data.get("lender_clawback"), lender_reference=data.get("lender_reference", ""),
                resale_price=data.get("resale_price"), subsidy_handled=data.get("subsidy_handled", False),
                confirm_identifier=data["confirm_identifier"], manual_refund=data.get("manual_refund"),
                manual_refund_reason=data.get("manual_refund_reason", ""),
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"訂單 {order.number} 已辦理交車後退車。")
            return redirect("order_detail", pk=order.pk)
    snapshot = getattr(order, "legacy_snapshot", None)
    return render(request, "sales/order_return.html", {
        "order": order, "form": form, "blockers": blockers, "vehicle": vehicle, "ledger": ledger, "profile": profile,
        "received": received, "disbursed": disbursed, "subsidy": subsidy, "legacy": snapshot, "manual_cap": manual_cap,
        "impacts": [] if blockers else return_impacts(order, ledger=ledger, profile=profile, vehicle=vehicle),
        "identifier": vehicle.identifier if vehicle is not None else (snapshot.vehicle_identifier if snapshot else ""),
    })
