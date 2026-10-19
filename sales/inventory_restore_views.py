"""車輛「改回現有庫存」確認頁（admin only，路由列在 ROOT_ONLY）。"""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from sales.access.services import is_root
from sales.models import VehicleInventory
from sales.services.inventory_restore import (
    ACKNOWLEDGE_STATUSES, CONFIRM_FALLBACK, MODE_NEW, MODE_REGISTERED, REASON_LIMIT, deletion_review_order, identifier_matches,
    identifier_tail, registration_trace, restore_blockers, restore_impacts, restore_to_stock,
)


class InventoryRestoreForm(forms.Form):
    expected_updated_at = forms.CharField(widget=forms.HiddenInput)
    mode = forms.ChoiceField(label="改回方式", required=False, widget=forms.RadioSelect, choices=(
        (MODE_NEW, "當新車：原本的領牌資料有誤，車輛沒有真的領牌"),
        (MODE_REGISTERED, "當已領牌車：保留車牌，之後只能以領牌車交易再售"),
    ))
    resale_price = forms.IntegerField(label="領牌車再售價", required=False, min_value=1,
        widget=forms.NumberInput(attrs={"class": "form-control", "inputmode": "numeric", "placeholder": "例如 52000"}))
    confirm_identifier = forms.CharField(label="輸入引擎／車身號碼末 4 碼確認", required=False, max_length=12,
        widget=forms.TextInput(attrs={"class": "form-control restore-confirm-input", "autocomplete": "off", "autocapitalize": "characters",
                                      "spellcheck": "false", "placeholder": "末 4 碼"}))
    reason = forms.CharField(label="改回原因", max_length=REASON_LIMIT, widget=forms.Textarea(attrs={
        "class": "form-control", "rows": 3, "placeholder": "例如：刪單後確認車在店內、沒有領牌；匯入時誤標已售出"}))

    def __init__(self, *args, trace=None, vehicle=None, needs_ack=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.trace, self.vehicle = trace, vehicle
        if trace:
            self.fields["mode"].required = True
            if not trace["plate"]:
                self.fields["mode"].choices = self.fields["mode"].choices[:1]
        else:
            self.fields.pop("mode")
            self.fields.pop("resale_price")
        if needs_ack:
            field = self.fields["confirm_identifier"]
            field.required = True
            if identifier_tail(vehicle) == CONFIRM_FALLBACK:
                field.label, field.widget.attrs["placeholder"] = f"這台車沒有識別號碼，請輸入「{CONFIRM_FALLBACK}」", CONFIRM_FALLBACK
        else:
            self.fields.pop("confirm_identifier")

    def clean(self):
        data = super().clean()
        if self.trace and data.get("mode") == MODE_REGISTERED and not data.get("resale_price"):
            self.add_error("resale_price", "當已領牌車改回時，請填寫再售價。")
        if "confirm_identifier" in self.fields and data.get("confirm_identifier") and not identifier_matches(self.vehicle, data["confirm_identifier"]):
            self.add_error("confirm_identifier", "號碼不符，請對照上方的引擎／車身號碼再輸入一次。")
        return data


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def inventory_restore(request, pk):
    if not is_root(request.user):
        raise PermissionDenied("只有 admin 可以把車輛改回現有庫存。")
    vehicle = get_object_or_404(VehicleInventory.objects.select_related(
        "vehicle_model", "color", "current_dealer", "disposition_dealer"), pk=pk)
    review = deletion_review_order(vehicle)
    trace = registration_trace(vehicle, review)
    blockers = restore_blockers(vehicle)
    form = InventoryRestoreForm(request.POST if request.method == "POST" else None, trace=trace, vehicle=vehicle,
        needs_ack=vehicle.status in ACKNOWLEDGE_STATUSES,
        initial={"expected_updated_at": vehicle.updated_at.isoformat(), "mode": "" if trace else MODE_NEW})
    if request.method == "POST" and not blockers and form.is_valid():
        try:
            restore_to_stock(
                user=request.user, vehicle_id=vehicle.pk, reason=form.cleaned_data["reason"],
                expected_updated_at=form.cleaned_data["expected_updated_at"],
                actor_name=request.user.get_full_name() or request.user.get_username(),
                mode=form.cleaned_data.get("mode") or "", resale_price=form.cleaned_data.get("resale_price"),
                confirm_identifier=form.cleaned_data.get("confirm_identifier", ""),
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"{vehicle.identifier} 已改回現有庫存（可銷售）。")
            return redirect("inventory_edit", pk=vehicle.pk)
    return render(request, "sales/inventory_restore.html", {
        "vehicle": vehicle, "form": form, "blockers": blockers, "impacts": restore_impacts(vehicle),
        "review_order": review, "trace": trace, "needs_ack": vehicle.status in ACKNOWLEDGE_STATUSES,
    })
