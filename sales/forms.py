from django import forms
from django.forms import inlineformset_factory

from .models import (
    AccessoryLine,
    OtherFeeLine,
    SalesOrder,
    SalesSource,
    VehicleColor,
    VehicleInventory,
)


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("format", "%Y-%m-%d")
        super().__init__(*args, **kwargs)


class SalesOrderForm(forms.ModelForm):
    class Meta:
        model = SalesOrder
        fields = [
            "source_type",
            "source",
            "owner_type",
            "owner_name",
            "owner_name_en",
            "owner_phone",
            "owner_email",
            "owner_birth_date",
            "owner_nationality",
            "owner_address",
            "owner_id_number",
            "residence_expiry",
            "id_front",
            "id_back",
            "id_verified",
            "vehicle_model",
            "color",
            "payment_type",
            "vehicle_price",
            "plate_insurance_fee",
            "installment_opening_fee",
            "deposit_amount",
            "deposit_date",
            "deposit_method",
            "installment_company",
            "installment_periods",
            "installment_monthly",
            "is_trade_in_subsidy",
            "trade_in_plate",
            "subsidy_type",
            "old_vehicle_valuation",
            "old_vehicle_tax",
            "plate_choice",
            "watched_numbers",
            "plate_preference_note",
            "delivery_method",
            "note",
        ]
        widgets = {
            "owner_birth_date": DateInput(),
            "residence_expiry": DateInput(),
            "deposit_date": DateInput(),
            "owner_address": forms.Textarea(attrs={"rows": 2}),
            "note": forms.Textarea(attrs={"rows": 3}),
            "balance_adjustment_reason": forms.Textarea(attrs={"rows": 2}),
            "watched_numbers": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "每行一個號碼，依志願序排列",
                }
            ),
            "plate_preference_note": forms.Textarea(
                attrs={"rows": 2, "placeholder": "例如：不要諧音、避開 4、尾數要大"}
            ),
            "id_front": forms.ClearableFileInput(
                attrs={"accept": "image/*"}
            ),
            "id_back": forms.ClearableFileInput(
                attrs={"accept": "image/*"}
            ),
        }

    def __init__(self, *args, existing_documents=None, **kwargs):
        self.existing_documents = existing_documents or {}
        super().__init__(*args, **kwargs)
        self.fields["source"].queryset = SalesSource.objects.filter(active=True)
        self.fields["color"].queryset = VehicleColor.objects.filter(active=True)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        self.fields["id_verified"].widget.attrs["class"] = "form-check"
        self.fields["is_trade_in_subsidy"].widget.attrs["class"] = "form-check"

    def clean(self):
        data = super().clean()
        source_type = data.get("source_type")
        source = data.get("source")
        if source_type == SalesOrder.SourceType.STORE:
            data["source"] = None
            self.cleaned_data["source"] = None
        elif source and source.source_type != source_type:
            self.add_error("source", "來源名稱與選擇的訂單來源不一致。")

        model = data.get("vehicle_model")
        color = data.get("color")
        if model and color and color.vehicle_model_id != model.id:
            self.add_error("color", "請選擇此車型可用的車色。")

        if data.get("owner_type") == SalesOrder.OwnerType.LOCAL:
            for field_name in ("id_front", "id_back"):
                if (
                    not data.get(field_name)
                    and not getattr(self.instance, field_name)
                    and not self.existing_documents.get(field_name)
                ):
                    self.add_error(field_name, "本國自然人需上傳身分證正反面。")
        if not data.get("id_verified"):
            self.add_error("id_verified", "請對照證件並確認資料正確。")
        return data


AccessoryFormSet = inlineformset_factory(
    SalesOrder,
    AccessoryLine,
    fields=["name", "quantity", "line_type", "amount", "installed_on", "note"],
    widgets={"installed_on": DateInput()},
    extra=1,
    can_delete=True,
)

OtherFeeFormSet = inlineformset_factory(
    SalesOrder,
    OtherFeeLine,
    fields=["name", "amount"],
    extra=1,
    can_delete=True,
)


class VehicleInventoryForm(forms.ModelForm):
    class Meta:
        model = VehicleInventory
        fields = [
            "vehicle_model",
            "color",
            "engine_number",
            "frame_number",
            "ownership_store",
            "location_store",
            "received_on",
            "condition_note",
            "condition_photo",
            "condition_resolution",
        ]
        widgets = {
            "received_on": DateInput(),
            "condition_note": forms.Textarea(attrs={"rows": 3}),
            "condition_resolution": forms.Textarea(attrs={"rows": 3}),
            "condition_photo": forms.ClearableFileInput(
                attrs={"accept": "image/*", "capture": "environment"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["color"].queryset = VehicleColor.objects.filter(active=True)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class SignedContractForm(forms.ModelForm):
    class Meta:
        model = SalesOrder
        fields = ["signed_contract"]
        widgets = {
            "signed_contract": forms.ClearableFileInput(
                attrs={"accept": "image/*,application/pdf", "capture": "environment"}
            )
        }


class AllocationForm(forms.Form):
    vehicle = forms.ModelChoiceField(
        label="實體車輛", queryset=VehicleInventory.objects.none()
    )

    def __init__(self, order, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vehicle"].queryset = VehicleInventory.objects.filter(
            vehicle_model=order.vehicle_model,
            color=order.color,
            status=VehicleInventory.Status.AVAILABLE,
        ).select_related("location_store", "vehicle_model", "color")
        self.fields["vehicle"].widget.attrs["class"] = "form-control"
