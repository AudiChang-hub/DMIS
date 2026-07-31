from decimal import Decimal
from pathlib import Path

from django import forms
from django.db.models import Q
from django.forms import BaseFormSet, formset_factory, inlineformset_factory
from django.forms.models import BaseInlineFormSet
from django.utils import timezone

from .models import (
    AccessoryLine,
    OtherFeeLine,
    OrderOperationsProfile,
    PaymentRecord,
    RegistrationDocument,
    SalesOrder,
    SalesSource,
    SubsidyDocument,
    VehicleColor,
    VehicleInventory,
    VehicleModel,
    VehicleSettlementCostRule,
)
from .services.registration_fee import (
    UnsupportedRegistrationFee,
    calculate_registration_fee,
)


PHONE_FIELDS = {"owner_phone"}
EMAIL_FIELDS = {"owner_email"}
LATIN_IDENTIFIER_FIELDS = {
    "owner_id_number",
    "trade_in_plate",
    "old_owner_id_number",
    "watched_numbers",
    "engine_number",
    "frame_number",
}
ENGLISH_TEXT_FIELDS = {"owner_name_en"}


def apply_mobile_keyboard_attrs(form):
    """Give mobile browsers the best available keyboard hint per field."""
    for field_name, field in form.fields.items():
        widget = field.widget
        if isinstance(widget, (forms.HiddenInput, forms.FileInput)):
            continue
        if field_name in PHONE_FIELDS:
            widget.attrs.update(
                {
                    "inputmode": "tel",
                    "autocomplete": "tel",
                    "autocapitalize": "none",
                }
            )
        elif field_name in EMAIL_FIELDS:
            widget.attrs.update(
                {
                    "inputmode": "email",
                    "autocomplete": "email",
                    "autocapitalize": "none",
                    "spellcheck": "false",
                }
            )
        elif field_name in LATIN_IDENTIFIER_FIELDS:
            widget.attrs.update(
                {
                    "inputmode": "text",
                    "lang": "en",
                    "autocapitalize": "characters",
                    "spellcheck": "false",
                    "autocomplete": "off",
                }
            )
        elif field_name in ENGLISH_TEXT_FIELDS:
            widget.attrs.update(
                {
                    "inputmode": "text",
                    "lang": "en",
                    "autocapitalize": "words",
                    "spellcheck": "false",
                }
            )
        elif isinstance(field, forms.DecimalField):
            widget.attrs.setdefault("inputmode", "decimal")
        elif isinstance(field, forms.IntegerField):
            widget.attrs.setdefault("inputmode", "numeric")
        elif isinstance(widget, (forms.TextInput, forms.Textarea)):
            widget.attrs.update(
                {
                    "inputmode": "text",
                    "lang": "zh-Hant",
                    "autocapitalize": "none",
                }
            )


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("format", "%Y-%m-%d")
        super().__init__(*args, **kwargs)


class SalesOrderForm(forms.ModelForm):
    vehicle_energy_type = forms.ChoiceField(
        label="動力類型",
        choices=VehicleModel.EnergyType.choices,
        required=False,
    )
    registration_calculated_total = forms.DecimalField(
        label="系統試算牌險合計",
        max_digits=12,
        decimal_places=0,
        required=False,
    )

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
            "vehicle_category",
            "registration_date",
            "compulsory_insurance_period",
            "registration_plate_fee",
            "registration_license_fee",
            "registration_inspection_fee",
            "road_maintenance_fee",
            "license_tax_fee",
            "compulsory_insurance_fee",
            "plate_selection_fee",
            "lien_registration_fee",
            "registration_calculated_total",
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
            "old_owner_same_as_owner",
            "plate_choice",
            "watched_numbers",
            "plate_preference_note",
            "delivery_method",
            "delivery_destination",
            "note",
        ]
        widgets = {
            "owner_birth_date": DateInput(),
            "residence_expiry": DateInput(),
            "deposit_date": DateInput(),
            "registration_date": DateInput(),
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
        self._previous_plate_insurance_fee = self.instance.plate_insurance_fee
        self._plate_fee_was_automatic = (
            not self.instance.pk
            or self.instance.plate_insurance_fee
            == self.instance.registration_calculated_total
        )
        if not self.is_bound:
            blank_numeric_fields = (
                "vehicle_price",
                "plate_insurance_fee",
                "installment_opening_fee",
                "deposit_amount",
                "installment_periods",
                "installment_monthly",
                "plate_selection_fee",
                "lien_registration_fee",
            )
            for field_name in blank_numeric_fields:
                if field_name not in self.initial:
                    self.fields[field_name].initial = None
        self.fields["source"].queryset = SalesSource.objects.filter(active=True)
        self.fields["color"].queryset = VehicleColor.objects.filter(active=True)
        self.fields["registration_date"].required = False
        self.fields["compulsory_insurance_period"].initial = (
            SalesOrder.CompulsoryInsurancePeriod.ONE_YEAR
        )
        self.fields["compulsory_insurance_period"].required = False
        self.fields["plate_selection_fee"].required = False
        self.fields["lien_registration_fee"].required = False
        if self.instance.pk and self.instance.vehicle_model_id:
            self.fields["vehicle_energy_type"].initial = (
                self.instance.vehicle_model.energy_type
            )
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        apply_mobile_keyboard_attrs(self)
        for field_name in (
            "registration_plate_fee",
            "registration_license_fee",
            "registration_inspection_fee",
            "road_maintenance_fee",
            "license_tax_fee",
            "compulsory_insurance_fee",
            "registration_calculated_total",
        ):
            self.fields[field_name].required = False
            self.fields[field_name].widget.attrs["readonly"] = True
            self.fields[field_name].widget.attrs["tabindex"] = "-1"
        self.fields["plate_insurance_fee"].required = False
        for field_name in (
            "installment_company",
            "installment_periods",
            "installment_opening_fee",
            "installment_monthly",
        ):
            self.fields[field_name].required = False
        self.fields["id_verified"].widget.attrs["class"] = "form-check"
        self.fields["is_trade_in_subsidy"].widget.attrs["class"] = "form-check"
        self.fields["old_owner_same_as_owner"].widget.attrs["class"] = "form-check"
        self.fields["delivery_method"].required = True
        self.fields["vehicle_category"].required = False
        self.fields["vehicle_category"].initial = SalesOrder.VehicleCategory.NEW

    def clean(self):
        data = super().clean()
        if not data.get("vehicle_category"):
            data["vehicle_category"] = SalesOrder.VehicleCategory.NEW
            self.cleaned_data["vehicle_category"] = SalesOrder.VehicleCategory.NEW
        source_type = data.get("source_type")
        source = data.get("source")
        if source_type == SalesOrder.SourceType.STORE:
            data["source"] = None
            self.cleaned_data["source"] = None
        elif source and source.source_type != source_type:
            self.add_error("source", "來源名稱與選擇的訂單來源不一致。")

        model = data.get("vehicle_model")
        selected_energy_type = data.get("vehicle_energy_type")
        if model and selected_energy_type and model.energy_type != selected_energy_type:
            self.add_error("vehicle_model", "所選車型與動力類型不一致。")
        if model and not selected_energy_type:
            data["vehicle_energy_type"] = model.energy_type
            self.cleaned_data["vehicle_energy_type"] = model.energy_type
        color = data.get("color")
        if model and color and color.vehicle_model_id != model.id:
            self.add_error("color", "請選擇此車型可用的車色。")

        installment_fields = (
            "installment_company",
            "installment_periods",
            "installment_opening_fee",
            "installment_monthly",
        )
        if data.get("payment_type") == SalesOrder.PaymentType.INSTALLMENT:
            for field_name in installment_fields:
                if data.get(field_name) in (None, ""):
                    self.add_error(field_name, "選擇分期付款時，此欄位為必填。")
        else:
            for field_name in installment_fields:
                value = "" if field_name == "installment_company" else 0
                data[field_name] = value
                self.cleaned_data[field_name] = value

        registration_date = data.get("registration_date")
        insurance_period = (
            data.get("compulsory_insurance_period")
            or SalesOrder.CompulsoryInsurancePeriod.ONE_YEAR
        )
        data["compulsory_insurance_period"] = insurance_period
        self.cleaned_data["compulsory_insurance_period"] = insurance_period
        for field_name in ("plate_selection_fee", "lien_registration_fee"):
            if data.get(field_name) is None:
                data[field_name] = 0
                self.cleaned_data[field_name] = 0
        if model and model.energy_type == VehicleModel.EnergyType.GAS:
            if registration_date and model.displacement_cc:
                try:
                    result = calculate_registration_fee(
                        model.displacement_cc,
                        registration_date,
                        insurance_period,
                    )
                except UnsupportedRegistrationFee as exc:
                    self.add_error("vehicle_model", str(exc))
                else:
                    calculated_fields = {
                        "registration_rate_class": result.rate_class,
                        "registration_plate_fee": result.plate_fee,
                        "registration_license_fee": result.license_fee,
                        "registration_inspection_fee": result.inspection_fee,
                        "road_maintenance_fee": result.road_maintenance_fee,
                        "license_tax_fee": result.license_tax_fee,
                        "compulsory_insurance_fee": result.compulsory_insurance_fee,
                    }
                    for field_name, value in calculated_fields.items():
                        data[field_name] = value
                        self.cleaned_data[field_name] = value
                    calculated_total = (
                        result.fixed_and_variable_total
                        + data["plate_selection_fee"]
                        + data["lien_registration_fee"]
                    )
                    data["registration_calculated_total"] = calculated_total
                    self.cleaned_data["registration_calculated_total"] = (
                        calculated_total
                    )
                    self.instance.registration_rate_class = result.rate_class
                    self.instance.registration_calculated_total = calculated_total
                    if (
                        data.get("plate_insurance_fee") is None
                        or (
                            self._plate_fee_was_automatic
                            and data.get("plate_insurance_fee")
                            == self._previous_plate_insurance_fee
                        )
                    ):
                        data["plate_insurance_fee"] = calculated_total
                        self.cleaned_data["plate_insurance_fee"] = calculated_total
            else:
                self.instance.registration_rate_class = ""
                self.instance.registration_calculated_total = 0
        elif model:
            self.instance.registration_rate_class = ""
            self.instance.registration_calculated_total = 0
            for field_name in (
                "registration_plate_fee",
                "registration_license_fee",
                "registration_inspection_fee",
                "road_maintenance_fee",
                "license_tax_fee",
                "compulsory_insurance_fee",
                "registration_calculated_total",
            ):
                data[field_name] = 0
                self.cleaned_data[field_name] = 0

        if data.get("delivery_method") in {
            SalesOrder.DeliveryMethod.DIRECT_DELIVERY,
            SalesOrder.DeliveryMethod.CARRIER,
        } and not data.get("delivery_destination"):
            self.add_error(
                "delivery_destination",
                "送至指定地點或委託託運時必須填寫目的地。",
            )

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


class OrderEditForm(SalesOrderForm):
    change_reason = forms.CharField(
        label="變更原因",
        required=True,
        widget=forms.Textarea(
            attrs={"rows": 2, "placeholder": "請說明本次修改原因"}
        ),
    )

    def clean(self):
        data = super().clean()
        if (
            self.instance.actual_balance != self.instance.calculated_balance
            and not self.instance.balance_adjustment_reason
            and data.get("change_reason")
        ):
            self.instance.balance_adjustment_reason = data["change_reason"]
        if self.instance.allocated_vehicle_id:
            if (
                data.get("vehicle_model")
                and data["vehicle_model"].pk != self.instance.vehicle_model_id
            ):
                self.add_error("vehicle_model", "訂單已配車，需先解除配車才能修改車型。")
            if data.get("color") and data["color"].pk != self.instance.color_id:
                self.add_error("color", "訂單已配車，需先解除配車才能修改車色。")
        return data


class AccessoryLineForm(forms.ModelForm):
    class Meta:
        model = AccessoryLine
        fields = ["name", "quantity", "line_type", "amount", "installed_on", "note"]
        widgets = {"installed_on": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ("name", "quantity", "line_type", "amount"):
            self.fields[field_name].required = False
        apply_mobile_keyboard_attrs(self)
        if not self.is_bound and not self.instance.pk and "amount" not in self.initial:
            self.fields["amount"].initial = None

    def clean(self):
        data = super().clean()
        if not data.get("name"):
            data["DELETE"] = True
            self.cleaned_data["DELETE"] = True
            return data

        for field_name in ("quantity", "line_type", "amount"):
            if data.get(field_name) in (None, ""):
                self.add_error(field_name, "填寫配件名稱後，此欄位為必填。")
        return data


AccessoryFormSet = inlineformset_factory(
    SalesOrder,
    AccessoryLine,
    form=AccessoryLineForm,
    extra=1,
    can_delete=True,
)


class OtherFeeLineForm(forms.ModelForm):
    class Meta:
        model = OtherFeeLine
        fields = ["name", "amount"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].required = False
        self.fields["amount"].required = False
        apply_mobile_keyboard_attrs(self)
        if not self.is_bound and not self.instance.pk and "amount" not in self.initial:
            self.fields["amount"].initial = None

    def clean(self):
        data = super().clean()
        name = (data.get("name") or "").strip()
        amount = data.get("amount")
        if not name and amount in (None, ""):
            data["DELETE"] = True
            self.cleaned_data["DELETE"] = True
            return data
        if not name:
            self.add_error("name", "填寫金額後，請輸入費用項目名稱。")
        if amount in (None, ""):
            self.add_error("amount", "填寫費用項目後，請輸入金額。")
        return data


OtherFeeFormSet = inlineformset_factory(
    SalesOrder,
    OtherFeeLine,
    form=OtherFeeLineForm,
    extra=1,
    can_delete=True,
)


class VehicleInventoryForm(forms.ModelForm):
    change_reason = forms.CharField(
        label="異動原因（選填）",
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 2, "placeholder": "例如：調度至倉庫、車況複檢、資料更正"}
        ),
    )
    CORE_FIELDS = (
        "vehicle_model",
        "color",
        "engine_number",
        "frame_number",
        "received_on",
    )
    CORE_LOCKED_STATUSES = {
        VehicleInventory.Status.RESERVED,
        VehicleInventory.Status.TRANSFER_PENDING,
        VehicleInventory.Status.IN_TRANSFER,
        VehicleInventory.Status.DELIVERY_PENDING,
        VehicleInventory.Status.DELIVERED,
        VehicleInventory.Status.SOLD,
    }
    FINAL_STATUSES = {
        VehicleInventory.Status.DELIVERED,
        VehicleInventory.Status.SOLD,
    }

    class Meta:
        model = VehicleInventory
        fields = [
            "vehicle_model",
            "color",
            "engine_number",
            "frame_number",
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
        if not self.instance.pk:
            self.fields.pop("change_reason", None)
        self.fields["color"].queryset = VehicleColor.objects.filter(active=True)
        self.core_fields_locked = bool(
            self.instance.pk
            and self.instance.status in self.CORE_LOCKED_STATUSES
        )
        self.final_fields_locked = bool(
            self.instance.pk and self.instance.status in self.FINAL_STATUSES
        )
        if self.instance.pk and self.instance.color_id:
            self.fields["color"].queryset = VehicleColor.objects.filter(
                Q(active=True) | Q(pk=self.instance.color_id)
            )
        if self.core_fields_locked:
            locked_fields = list(self.CORE_FIELDS)
            if self.final_fields_locked:
                locked_fields.append("location_store")
            for field_name in locked_fields:
                self.fields[field_name].disabled = True
                self.fields[field_name].help_text = (
                    "此車輛已完成交付，僅可補充車況與處理紀錄。"
                    if self.final_fields_locked
                    else "此車輛已進入配車或交付流程，為避免訂單資料不一致，目前不可修改。"
                )
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        apply_mobile_keyboard_attrs(self)

    def save(self, commit=True):
        vehicle = super().save(commit=False)
        if not vehicle.ownership_store_id:
            vehicle.ownership_store = vehicle.location_store
        if commit:
            vehicle.save()
            self.save_m2m()
        return vehicle


class VehicleModelMasterForm(forms.ModelForm):
    class Meta:
        model = VehicleModel
        fields = [
            "brand",
            "energy_type",
            "name",
            "model_number",
            "model_year",
            "model_code",
            "displacement_cc",
            "suggested_price",
            "active",
        ]
        labels = {
            "brand": "品牌",
            "energy_type": "能源別",
            "name": "機種",
            "model_number": "型號",
            "model_code": "型式",
        }
        widgets = {
            "model_year": forms.NumberInput(
                attrs={"min": "1900", "max": "2200", "inputmode": "numeric"}
            ),
            "displacement_cc": forms.NumberInput(attrs={"inputmode": "numeric"}),
            "suggested_price": forms.NumberInput(attrs={"inputmode": "numeric"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["model_year"].required = True
        self.fields["model_number"].required = True
        self.fields["model_code"].required = True
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        apply_mobile_keyboard_attrs(self)

    def clean(self):
        cleaned = super().clean()
        brand = (cleaned.get("brand") or "").strip()
        name = (cleaned.get("name") or "").strip()
        model_number = (cleaned.get("model_number") or "").strip()
        model_code = (cleaned.get("model_code") or "").strip()
        model_year = cleaned.get("model_year")
        duplicate = VehicleModel.objects.filter(
            brand__iexact=brand,
            name__iexact=name,
            model_number__iexact=model_number,
            model_year=model_year,
            model_code=model_code,
        )
        if self.instance.pk:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if (
            brand
            and name
            and model_number
            and model_year
            and model_code
            and duplicate.exists()
        ):
            raise forms.ValidationError(
                "相同品牌、機種、型號、年份及型式的車型已存在。"
            )
        if (
            self.instance.pk
            and self.instance.vehicleinventory_set.exists()
            and cleaned.get("energy_type") != self.instance.energy_type
        ):
            self.add_error(
                "energy_type",
                "此車型已有庫存資料，為避免引擎／車身號碼規則失效，不能變更能源別。",
            )
        return cleaned


class VehicleSettlementCostRuleForm(forms.ModelForm):
    class Meta:
        model = VehicleSettlementCostRule
        fields = [
            "vehicle_model",
            "registration_county",
            "amount",
            "announced_on",
            "effective_from",
            "effective_to",
            "note",
            "active",
        ]
        widgets = {
            "amount": forms.NumberInput(attrs={"inputmode": "numeric"}),
            "announced_on": DateInput(),
            "effective_from": DateInput(),
            "effective_to": DateInput(),
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["registration_county"].required = False
        county_choices = list(self.fields["registration_county"].choices)
        self.fields["registration_county"].choices = [
            ("", "全國預設"),
            *county_choices[1:],
        ]
        self.fields["vehicle_model"].queryset = VehicleModel.objects.filter(
            active=True
        ).order_by("brand", "name", "-model_year")
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        apply_mobile_keyboard_attrs(self)

class VehicleColorMasterForm(forms.ModelForm):
    class Meta:
        model = VehicleColor
        fields = ["name", "active"]
        labels = {"name": "顏色"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class BaseVehicleColorFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        names = {}
        for index, form in enumerate(self.forms, start=1):
            if not hasattr(form, "cleaned_data"):
                continue
            if form.cleaned_data.get("DELETE"):
                color = form.instance
                if color.pk and (
                    color.vehicleinventory_set.exists()
                    or color.salesorder_set.exists()
                ):
                    raise forms.ValidationError(
                        f"顏色「{color.name}」已有訂單或庫存使用，不能刪除；請改為停用。"
                    )
                continue
            name = (form.cleaned_data.get("name") or "").strip()
            if not name:
                continue
            key = name.casefold()
            if key in names:
                form.add_error("name", f"與第 {names[key]} 列顏色重複。")
            else:
                names[key] = index


VehicleColorMasterFormSet = inlineformset_factory(
    VehicleModel,
    VehicleColor,
    form=VehicleColorMasterForm,
    formset=BaseVehicleColorFormSet,
    extra=1,
    can_delete=True,
)


class OrderOperationsForm(forms.ModelForm):
    vehicle_control_password = forms.CharField(
        label="車控密碼",
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="留空表示保留目前密碼。",
    )
    battery_password = forms.CharField(
        label="電池合約密碼",
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="留空表示保留目前密碼。",
    )
    change_reason = forms.CharField(
        label="本次更新說明（選填）",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    class Meta:
        model = OrderOperationsProfile
        exclude = [
            "order",
            "vehicle_cost_manual",
            "vehicle_cost_rule",
            "vehicle_cost_registration_date",
            "vehicle_cost_county",
            "vehicle_cost_locked_at",
            "vehicle_cost_locked_by",
            "manual_financial_fields",
            "vehicle_control_password_encrypted",
            "battery_password_encrypted",
            "updated_by",
        ]
        widgets = {
            "invoice_date": DateInput(),
            "subsidy_applied_on": DateInput(),
            "old_vehicle_manufactured_on": DateInput(),
            "scrapped_on": DateInput(),
            "recycled_on": DateInput(),
            "battery_activated_on": DateInput(),
            "other_fulfillment": forms.Textarea(attrs={"rows": 2}),
            "installment_info": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        synced_fields = {
            "dealer_name",
            "actual_disbursement",
            "vehicle_cost",
            "installment_fee_income",
            "installment_info",
            "payment_confirmed",
            "installment_transfer_confirmed",
        }
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")
            if name in synced_fields:
                field.disabled = True
                field.help_text = "由訂單或收款紀錄自動同步。"
            if isinstance(field, forms.DecimalField):
                field.required = False
                if name in {
                    "registration_tax_expense",
                    "compulsory_insurance_expense",
                    "plate_selection_expense",
                    "registration_tax_income",
                    "compulsory_insurance_income",
                    "plate_selection_income",
                }:
                    field.help_text = (
                        "系統會先帶入，可人工修改；修改後不再被訂單同步覆蓋。"
                    )
                if not self.is_bound and self.initial.get(name) in (None, 0, Decimal("0")):
                    self.initial[name] = ""
        apply_mobile_keyboard_attrs(self)

    def clean(self):
        cleaned = super().clean()
        for name, field in self.fields.items():
            if isinstance(field, forms.DecimalField) and cleaned.get(name) is None:
                cleaned[name] = Decimal("0")
        return cleaned


class PaymentRecordForm(forms.ModelForm):
    class Meta:
        model = PaymentRecord
        fields = [
            "item_name",
            "expected_amount",
            "received_amount",
            "received_on",
            "payment_method",
            "receiving_account",
            "confirmed",
            "proof",
            "note",
        ]
        widgets = {
            "received_on": DateInput(),
            "proof": forms.ClearableFileInput(
                attrs={"accept": "image/*,application/pdf"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.system_key:
            for name in ("item_name", "expected_amount", "payment_method"):
                self.fields[name].disabled = True
                self.fields[name].help_text = "由訂單自動同步。"
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")
            if (
                isinstance(field, forms.DecimalField)
                and not self.is_bound
                and self.initial.get(name) in (None, 0, Decimal("0"))
            ):
                self.initial[name] = ""
        apply_mobile_keyboard_attrs(self)


PaymentRecordFormSet = inlineformset_factory(
    SalesOrder,
    PaymentRecord,
    form=PaymentRecordForm,
    extra=1,
    can_delete=True,
)


class QuickInventoryEntryForm(forms.Form):
    vehicle_model = forms.ModelChoiceField(
        label="車型",
        queryset=VehicleModel.objects.none(),
        empty_label="請選擇車型",
    )
    color = forms.ModelChoiceField(
        label="車色",
        queryset=VehicleColor.objects.none(),
        empty_label="請先選擇車型",
    )
    identifier = forms.CharField(
        label="引擎／車身號碼",
        max_length=80,
        widget=forms.TextInput(attrs={"autocomplete": "off", "autocapitalize": "characters"}),
    )
    received_on = forms.DateField(
        label="進車日期",
        initial=timezone.localdate,
        widget=DateInput(),
    )
    condition_note = forms.CharField(
        label="車況說明",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "選填"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vehicle_model"].queryset = VehicleModel.objects.filter(
            active=True
        ).order_by("brand", "name")
        model_id = self.data.get(f"{self.prefix}-vehicle_model") if self.is_bound else None
        if model_id and str(model_id).isdigit():
            self.fields["color"].queryset = VehicleColor.objects.filter(
                active=True,
                vehicle_model_id=model_id,
            ).order_by("name")
            self.fields["color"].empty_label = "請選擇車色"
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        apply_mobile_keyboard_attrs(self)

    def clean_identifier(self):
        return self.cleaned_data["identifier"].strip().upper()

    def has_changed(self):
        changed = set(self.changed_data)
        changed.discard("received_on")
        return bool(changed)

    def clean(self):
        cleaned = super().clean()
        model = cleaned.get("vehicle_model")
        color = cleaned.get("color")
        if model and color and color.vehicle_model_id != model.pk:
            self.add_error("color", "此車色不屬於選定車型。")
        return cleaned


class BaseQuickInventoryEntryFormSet(BaseFormSet):
    def clean(self):
        super().clean()
        identifiers = {}
        active_forms = []
        for index, form in enumerate(self.forms, start=1):
            if not hasattr(form, "cleaned_data") or form.cleaned_data.get("DELETE"):
                continue
            if not form.has_changed():
                continue
            identifier = form.cleaned_data.get("identifier")
            if not identifier:
                continue
            active_forms.append((form, identifier))
            if identifier in identifiers:
                form.add_error(
                    "identifier",
                    f"與第 {identifiers[identifier]} 列重複。",
                )
            else:
                identifiers[identifier] = index
        if not active_forms:
            raise forms.ValidationError("請至少填寫一台車輛。")
        existing = set(
            VehicleInventory.objects.filter(
                Q(engine_number__in=identifiers) | Q(frame_number__in=identifiers)
            ).values_list("engine_number", "frame_number")
        )
        existing_identifiers = {
            value
            for pair in existing
            for value in pair
            if value
        }
        for form, identifier in active_forms:
            if identifier in existing_identifiers:
                form.add_error("identifier", "此號碼已存在於庫存資料。")


QuickInventoryEntryFormSet = formset_factory(
    QuickInventoryEntryForm,
    formset=BaseQuickInventoryEntryFormSet,
    extra=5,
    can_delete=True,
    max_num=100,
    validate_max=True,
)


class SignedContractForm(forms.ModelForm):
    class Meta:
        model = SalesOrder
        fields = ["signed_contract"]
        widgets = {
            "signed_contract": forms.ClearableFileInput(
                attrs={"accept": "image/*,application/pdf", "capture": "environment"}
            )
        }


class PrivacyConsentForm(forms.ModelForm):
    class Meta:
        model = SalesOrder
        fields = ["privacy_consent"]
        widgets = {
            "privacy_consent": forms.ClearableFileInput(
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


class ReallocationForm(AllocationForm):
    reason = forms.CharField(
        label="改配原因",
        max_length=250,
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "class": "form-control",
                "placeholder": "例如：原車車況異常，改配其他車輛",
            }
        ),
    )


class RegistrationStageForm(forms.ModelForm):
    class Meta:
        model = SalesOrder
        fields = ["registration_date", "registration_county", "final_plate_number"]
        widgets = {"registration_date": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._previous_calculated_total = (
            self.instance.registration_calculated_total
        )
        self._previous_actual_total = self.instance.plate_insurance_fee
        self._previous_calculated_balance = self.instance.calculated_balance
        self._previous_actual_balance = self.instance.actual_balance
        self.fields["registration_date"].required = True
        self.fields["registration_county"].required = True
        self.fields["final_plate_number"].required = True
        self.fields["final_plate_number"].widget.attrs.update(
            {
                "class": "form-control",
                "autocapitalize": "characters",
                "autocomplete": "off",
                "spellcheck": "false",
                "placeholder": "例如 ABC-1234",
            }
        )
        self.fields["registration_date"].widget.attrs["class"] = "form-control"
        self.fields["registration_county"].widget.attrs["class"] = "form-control"

    def clean_final_plate_number(self):
        return self.cleaned_data["final_plate_number"].strip().upper()

    def save(self, commit=True):
        order = super().save(commit=False)
        model = order.vehicle_model
        if (
            model.energy_type == VehicleModel.EnergyType.GAS
            and model.displacement_cc
            and order.registration_date
        ):
            result = calculate_registration_fee(
                model.displacement_cc,
                order.registration_date,
                order.compulsory_insurance_period,
            )
            order.registration_rate_class = result.rate_class
            order.registration_plate_fee = result.plate_fee
            order.registration_license_fee = result.license_fee
            order.registration_inspection_fee = result.inspection_fee
            order.road_maintenance_fee = result.road_maintenance_fee
            order.license_tax_fee = result.license_tax_fee
            order.compulsory_insurance_fee = result.compulsory_insurance_fee
            calculated_total = (
                result.fixed_and_variable_total
                + order.plate_selection_fee
                + order.lien_registration_fee
            )
            order.registration_calculated_total = calculated_total
            if (
                not self._previous_actual_total
                or self._previous_actual_total
                == self._previous_calculated_total
            ):
                order.plate_insurance_fee = calculated_total
            recalculated_balance = order.calculate_balance()
            if (
                self._previous_actual_balance == self._previous_calculated_balance
                or not order.balance_adjustment_reason
            ):
                order.actual_balance = recalculated_balance
        if commit:
            order.save()
        return order


class RegistrationDocumentUploadForm(forms.ModelForm):
    class Meta:
        model = RegistrationDocument
        fields = ["document_type", "name", "file"]
        widgets = {
            "document_type": forms.HiddenInput(),
            "file": forms.ClearableFileInput(
                attrs={
                    "accept": "image/jpeg,image/png,image/webp,application/pdf",
                    "capture": "environment",
                }
            ),
        }

    def clean(self):
        data = super().clean()
        if (
            data.get("document_type")
            == RegistrationDocument.DocumentType.OTHER_INSURANCE
            and not data.get("name")
        ):
            self.add_error("name", "新增其他保險單時必須填寫保險名稱。")
        upload = data.get("file")
        if upload and upload.content_type not in {
            "image/jpeg",
            "image/png",
            "image/webp",
            "application/pdf",
        }:
            self.add_error("file", "僅支援 JPG、PNG、WebP 或 PDF。")
        return data


class SubsidyDocumentUploadForm(forms.ModelForm):
    class Meta:
        model = SubsidyDocument
        fields = ["document_type", "name", "note", "file"]
        widgets = {
            "document_type": forms.HiddenInput(),
            "file": forms.ClearableFileInput(
                attrs={
                    "accept": (
                        "image/jpeg,image/png,image/webp,image/heic,image/heif,"
                        "application/pdf,.doc,.docx,.odt,.xls,.xlsx,.ods,.txt,.csv"
                    ),
                    "capture": "environment",
                }
            ),
        }

    def clean(self):
        data = super().clean()
        if (
            data.get("document_type") == SubsidyDocument.DocumentType.OTHER
            and not data.get("name")
        ):
            self.add_error("name", "其他補助文件必須填寫文件名稱。")
        return data

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if upload.size > 20 * 1024 * 1024:
            raise forms.ValidationError("單一檔案不可超過 20 MB。")
        extension = Path(upload.name).suffix.lower()
        allowed_extensions = {
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
            ".heic",
            ".heif",
            ".pdf",
            ".doc",
            ".docx",
            ".odt",
            ".xls",
            ".xlsx",
            ".ods",
            ".txt",
            ".csv",
        }
        allowed_content_types = {
            "image/jpeg",
            "image/png",
            "image/webp",
            "image/heic",
            "image/heif",
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.oasis.opendocument.text",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.oasis.opendocument.spreadsheet",
            "text/plain",
            "text/csv",
            "application/csv",
            "application/octet-stream",
        }
        if (
            extension not in allowed_extensions
            or upload.content_type not in allowed_content_types
        ):
            raise forms.ValidationError(
                "僅支援圖片、PDF、Word、Excel、ODT、ODS、TXT 或 CSV。"
            )
        return upload


class SubsidyDataForm(forms.ModelForm):
    change_reason = forms.CharField(
        label="變更原因",
        max_length=250,
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "placeholder": "例如：客戶補充舊車資料",
            }
        ),
    )

    class Meta:
        model = SalesOrder
        fields = [
            "is_trade_in_subsidy",
            "old_owner_same_as_owner",
            "trade_in_plate",
            "old_owner_name",
            "old_owner_id_number",
            "subsidy_type",
            "old_vehicle_valuation",
            "old_vehicle_tax",
        ]
        widgets = {
            "is_trade_in_subsidy": forms.CheckboxInput(),
            "old_owner_same_as_owner": forms.CheckboxInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        self.fields["is_trade_in_subsidy"].widget.attrs["class"] = "form-check"
        self.fields["old_owner_same_as_owner"].widget.attrs["class"] = "form-check"
        self.fields["trade_in_plate"].widget.attrs.update(
            {
                "lang": "en",
                "autocapitalize": "characters",
                "spellcheck": "false",
                "placeholder": "例如 ABC-1234",
            }
        )
        apply_mobile_keyboard_attrs(self)

    def clean_trade_in_plate(self):
        return self.cleaned_data["trade_in_plate"].strip().upper()

    def clean_old_owner_id_number(self):
        return self.cleaned_data["old_owner_id_number"].strip().upper()

    def clean(self):
        data = super().clean()
        for field_name in ("old_vehicle_valuation", "old_vehicle_tax"):
            if data.get(field_name) is None:
                data[field_name] = 0
                self.cleaned_data[field_name] = 0
        return data
