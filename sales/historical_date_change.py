"""admin 專用同買家領牌改期核對頁。"""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from sales.models import LegacyImportRow, SalesOrder
from sales.services.historical_replacement import require_admin
from sales.services.historical_date_change import date_change_preview, date_preview_token, change_historical_date


class HistoricalDateChangeForm(forms.Form):
    preview_token = forms.CharField(widget=forms.HiddenInput)
    date_kind = forms.ChoiceField(label="本次日期的性質", choices=[("", "請依實際狀況選擇"),
        ("planned", "預計領牌：尚未領牌且未交車"), ("actual", "已實際領牌：保留原交付進度")])
    same_buyer_confirmed = forms.BooleanField(label="已核對是同一位買家、同一台車的原訂單，不是退訂換人或另一筆交易")
    facts_confirmed = forms.BooleanField(label="已核對所選進度；若選預計領牌，原領牌及交付完成標記確為歷史匯入誤標")
    impact_confirmed = forms.BooleanField(label="已核對上述跨期與收支影響；本次只改日期及確認的進度，不更新其他 Excel 欄位，也不自動重算金額或發放獎勵")
    reason = forms.CharField(label="改期原因與核對說明", max_length=250, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, preview, **kwargs):
        super().__init__(*args, **kwargs)
        self.preview = preview
        for field in self.fields.values():
            if not isinstance(field.widget, (forms.HiddenInput, forms.CheckboxInput)):
                field.widget.attrs["class"] = "form-control"

    def clean(self):
        data = super().clean()
        day, order = self.preview["day"], self.preview["order"]
        if data.get("date_kind") == "actual":
            if not day or day > timezone.localdate():
                self.add_error("date_kind", "未來日期不能標記已實際領牌；若只是改期，請選預計領牌。")
            elif order.status != SalesOrder.Status.COMPLETED or not order.delivered_at:
                self.add_error("date_kind", "待辦訂單實際領牌請走原訂單的領牌流程，本頁不能取代正式領牌。")
            elif day > timezone.localtime(order.delivered_at).date():
                self.add_error("date_kind", "新領牌日期晚於既有交付日期，請先核對真實交付情況，不能只改領牌日期。")
        return data


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def historical_date_change(request, pk, row_pk, order_pk):
    require_admin(request.user)
    row = get_object_or_404(LegacyImportRow.objects.select_related("batch"), pk=row_pk, batch_id=pk)
    order = get_object_or_404(SalesOrder, pk=order_pk)
    preview = date_change_preview(row, order)
    correction = row.corrections.order_by("-created_at", "-pk").first()
    form = HistoricalDateChangeForm(request.POST if request.method == "POST" else None, preview=preview,
        initial={"preview_token": date_preview_token(preview, request.user), "reason": correction.reason[:250] if correction else ""})
    if request.method == "POST" and form.is_valid() and not preview["blockers"]:
        try:
            changed = change_historical_date(row_id=row.pk, order_id=order.pk, user=request.user, data=request.POST)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"已更新原訂單 {changed.number} 的領牌日期，未新增訂單；原配車與收支保留。")
            return redirect("order_detail", pk=changed.pk)
    return render(request, "sales/historical_date_change.html", {"preview": preview, "form": form},
        status=400 if request.method == "POST" else 200)
