"""admin 專用的歷史退訂換買家確認頁。"""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from sales.models import LegacyImportRow, SalesOrder
from sales.services.historical_replacement import (
    preview_token, replacement_preview, replace_historical_buyer, require_admin,
)


class HistoricalReplacementForm(forms.Form):
    preview_token = forms.CharField(widget=forms.HiddenInput)
    confirm_number = forms.CharField(label="輸入原訂單編號以確認", max_length=50)
    original_unregistered = forms.BooleanField(label="原買家未實際領牌（原領牌完成紀錄僅為歷史匯入誤標）")
    original_undelivered = forms.BooleanField(label="原買家未實際交車（原交付完成紀錄僅為歷史匯入誤標）")
    finances_checked = forms.BooleanField(label="已核對原單傭金、獎金、實物及所有收支，沒有未處理的款項或獎勵")
    incoming_status = forms.ChoiceField(label="新買家目前進度", choices=[("", "請依實際狀況選擇"), ("pending", "尚待領牌／交車"), ("completed", "已完成領牌及交車")])
    pending_vehicle_price = forms.DecimalField(label="新訂單成交車價", required=False, max_digits=12, decimal_places=0, min_value=1,
        help_text="依合約核對車價，不直接把 Excel 收款價當成車價。已完成的歷史銷售不需填。")
    pending_balance = forms.DecimalField(label="新訂單約定應收總額（含已收款）", required=False, max_digits=12, decimal_places=0, min_value=0,
        help_text="請勿先扣除已收款。本流程不另外扣訂金；本次 Excel 現金／刷卡會記為尾款實收，應收與實收分開保存。")
    collection_status = forms.ChoiceField(label="原買家款項狀況", choices=[("", "請依實際情況選擇"), ("none", "從未收款"), ("refunded", "曾收款，已全額退清")])
    actual_received = forms.DecimalField(label="原買家實際曾收款總額", max_digits=12, decimal_places=0, min_value=0,
        help_text="從未收款請填 0；曾收款請填已全額退清的金額，不會轉入新訂單。")
    refund_on = forms.DateField(label="實際退款日期", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    refund_method = forms.ChoiceField(label="退款方式", required=False, choices=[("", "請選擇")] + list(SalesOrder.PaymentMethod.choices))
    refund_reference = forms.CharField(label="退款憑據／查核依據", max_length=250, required=False)
    reason = forms.CharField(label="退訂原因與核對說明", max_length=250, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, preview, **kwargs):
        super().__init__(*args, **kwargs)
        self.preview = preview
        self.fields["confirm_number"].help_text = preview["order"].number
        for name, field in self.fields.items():
            if not isinstance(field.widget, (forms.CheckboxInput, forms.HiddenInput)):
                field.widget.attrs["class"] = "form-control"
            if field.help_text:
                field.widget.attrs["aria-describedby"] = f"id_{name}_help"

    def clean(self):
        data = super().clean()
        if data.get("confirm_number") != self.preview["order"].number:
            self.add_error("confirm_number", "編號必須與上方原訂單一致。")
        amount = data.get("actual_received")
        if data.get("incoming_status") == "completed":
            from django.utils.dateparse import parse_date
            try:
                completed_date = parse_date(str(self.preview["row"].mapped_data.get("registration_date") or ""))
            except ValueError:
                completed_date = None
            if not completed_date or completed_date > timezone.localdate():
                self.add_error("incoming_status", "已完成領牌時必須有有效的實際領牌日期，不能空白或填未來日期。")
        if data.get("incoming_status") == "pending":
            for key in ("pending_vehicle_price", "pending_balance"):
                if data.get(key) is None:
                    self.add_error(key, "尚待領牌／交車時，必須核對新訂單金額，不能沿用歷史匯入的零元應收。")
            from decimal import Decimal, InvalidOperation
            try:
                receipts = [Decimal(str(self.preview["row"].mapped_data.get(key) or 0)) for key in ("cash_received", "card_received")]
                if any(not value.is_finite() or value < 0 for value in receipts):
                    raise InvalidOperation
                received = sum(receipts, Decimal("0"))
                if data.get("pending_balance") is not None and data["pending_balance"] < received:
                    self.add_error("pending_balance", "應收尾款總額低於本次 Excel 實收，請先核對是否誤把已收金額再次扣除。")
            except InvalidOperation:
                self.add_error("pending_balance", "本次 Excel 收款金額格式異常，請先修正來源列。")
        if data.get("collection_status") == "none":
            if amount != 0 or self.preview["recorded_received"] > 0:
                self.add_error("collection_status", "原單已有收款紀錄或填入非零金額，不能選擇從未收款。請先核對。")
            data.update(refund_on=None, refund_method="", refund_reference="")
        elif data.get("collection_status") == "refunded":
            if amount is not None and (amount <= 0 or amount < self.preview["recorded_received"]):
                self.add_error("actual_received", "必須大於 0 且不低於系統已記錄收款，尚未全額退清不能使用此流程。")
            for key in ("refund_on", "refund_method", "refund_reference"):
                if not data.get(key):
                    self.add_error(key, "已退款時必須填寫，供後續查核。")
            if data.get("refund_on") and data["refund_on"] > timezone.localdate():
                self.add_error("refund_on", "必須是已完成退款的日期，不能填未來日期。")
        return data


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def historical_buyer_replacement(request, pk, row_pk, order_pk):
    require_admin(request.user)
    row = get_object_or_404(LegacyImportRow.objects.select_related("batch"), pk=row_pk, batch_id=pk)
    order = get_object_or_404(SalesOrder, pk=order_pk)
    preview = replacement_preview(row, order)
    latest_correction = row.corrections.order_by("-created_at", "-pk").first()
    form = HistoricalReplacementForm(request.POST if request.method == "POST" else None,
        preview=preview, initial={"preview_token": preview_token(preview, request.user),
            "reason": latest_correction.reason[:250] if latest_correction else "", "incoming_status": "pending"})
    if request.method == "POST" and form.is_valid() and not preview["blockers"]:
        try:
            new_order = replace_historical_buyer(row_id=row.pk, order_id=order.pk, user=request.user, data=request.POST)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"原訂單 {order.number} 已更正為退訂並保留原收支；{new_order.owner_name} 已補匯為 {new_order.number}。")
            return redirect("order_detail", pk=new_order.pk)
    return render(request, "sales/historical_buyer_replacement.html", {"preview": preview, "form": form},
                  status=400 if request.method == "POST" else 200)
