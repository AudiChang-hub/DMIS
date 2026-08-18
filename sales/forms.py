from decimal import Decimal
import re
from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q
from django.forms import BaseFormSet, formset_factory, inlineformset_factory
from django.forms.models import BaseInlineFormSet
from django.utils import timezone

from .models import (
    AccessoryProduct,
    AccessoryLine,
    BusinessHoliday,
    BrandRegistrationFeeRule,
    DealerVolumeBonusRule,
    DealerVolumeBonusSettlement,
    DealerVolumeBonusTier,
    DeliveryRecord,
    InstallmentCompany,
    InstallmentPlanOption,
    InstallmentPlanVersion,
    LegacyImportBatch,
    LegacyImportRow,
    OtherFeeLine,
    OrderOperationsProfile,
    PaymentRecord,
    PositionedPrintField,
    PositionedPrintTemplate,
    RegistrationDocument,
    SalesOrder,
    SalesSource,
    SalesSourceCategory,
    SalesSourceBrandPolicy,
    SalesSourceContact,
    SubsidyDocument,
    SubsidyItem,
    VehicleColor,
    VehicleInventory,
    VehicleIncentiveInstallmentRate,
    VehicleIncentiveRule,
    VehicleBrand,
    VehicleFactoryModelCode,
    VehicleModel,
    VehicleModelFamily,
    VehiclePriceVersion,
    VehicleSettlementCostRule,
    normalize_legacy_master_value,
    normalize_vehicle_identifier,
)
from .services.registration_fee import (
    UnsupportedRegistrationFee,
    calculate_registration_fee,
    calculate_vehicle_registration_fee,
)
from .services.installment_plan import resolve_installment_plan_option
from .services.positioned_template_pdf import PRINT_FIELD_CHOICES
from .services.upload_validation import (
    validate_document_upload,
    validate_excel_upload,
    validate_image_upload,
    validate_subsidy_upload,
    validate_template_background,
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
            "transaction_type",
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
        selected_source_type = (
            self.data.get("source_type")
            if self.is_bound
            else self.instance.source_type or SalesOrder.SourceType.STORE
        )
        self.fields["source"].queryset = SalesSource.objects.filter(
            active=True,
            source_type=selected_source_type,
        )
        self.fields["source"].required = False
        self.fields["source"].help_text = (
            "本店訂單可選擇承辦員工；合作車行與網路平台則必須選擇來源名稱。"
        )
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
        searchable_selects = {
            "source": "輸入車行或平台名稱",
            "vehicle_model": "輸入品牌、車型、型號或年份",
            "color": "輸入車色名稱",
        }
        for field_name, placeholder in searchable_selects.items():
            self.fields[field_name].widget.attrs.update(
                {
                    "data-searchable-select": "1",
                    "data-search-placeholder": placeholder,
                }
            )
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
        # 相容功能上線前建立的草稿與舊版表單送出；新畫面仍會顯示選項。
        self.fields["transaction_type"].required = False
        self.fields["transaction_type"].initial = SalesOrder.TransactionType.REGULAR_NEW

    def clean_id_front(self):
        return validate_image_upload(self.cleaned_data.get("id_front"))

    def clean_id_back(self):
        return validate_image_upload(self.cleaned_data.get("id_back"))

    def clean(self):
        data = super().clean()
        if not data.get("vehicle_category"):
            data["vehicle_category"] = SalesOrder.VehicleCategory.NEW
            self.cleaned_data["vehicle_category"] = SalesOrder.VehicleCategory.NEW
        if not data.get("transaction_type"):
            data["transaction_type"] = SalesOrder.TransactionType.REGULAR_NEW
            self.cleaned_data["transaction_type"] = SalesOrder.TransactionType.REGULAR_NEW
        source_type = data.get("source_type")
        source = data.get("source")
        if source and source.source_type != source_type:
            self.add_error("source", "來源名稱與選擇的訂單來源不一致。")

        if data.get("vehicle_category") == SalesOrder.VehicleCategory.USED:
            data["transaction_type"] = SalesOrder.TransactionType.USED
            self.cleaned_data["transaction_type"] = SalesOrder.TransactionType.USED
        elif data.get("transaction_type") == SalesOrder.TransactionType.USED:
            self.add_error("transaction_type", "中古車交易的車輛類別也必須選擇中古車。")

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
            option = resolve_installment_plan_option(
                model.pk if model else None,
                data.get("order_date") or self.instance.order_date or timezone.localdate(),
                data.get("installment_periods"),
            )
            if option:
                defaults = {
                    "installment_company": option.company.name,
                    "installment_opening_fee": option.opening_fee,
                    "installment_monthly": option.monthly_amount,
                }
                for field_name, value in defaults.items():
                    if data.get(field_name) in (None, ""):
                        data[field_name] = value
                        self.cleaned_data[field_name] = value
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
        if model and model.energy_type in {
            VehicleModel.EnergyType.GAS,
            VehicleModel.EnergyType.ELECTRIC,
        }:
            has_rate_basis = bool(
                model.displacement_cc
                if model.energy_type == VehicleModel.EnergyType.GAS
                else model.electric_registration_class
            )
            if registration_date and has_rate_basis:
                try:
                    result = calculate_vehicle_registration_fee(
                        model,
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

        # 新增訂單時尚未領牌是正常情境。前端會把唯讀試算欄位送成空字串，
        # DecimalField 會清理為 None，但模型欄位不接受 null；統一以 0 表示
        # 「尚未產生牌險金額」，後續填入領牌日期時仍會重新試算。
        for field_name in (
            "registration_calculated_total",
            "plate_insurance_fee",
        ):
            if data.get(field_name) is None:
                data[field_name] = Decimal("0")
                self.cleaned_data[field_name] = Decimal("0")

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


class SalesSourceForm(forms.ModelForm):
    class Meta:
        model = SalesSource
        fields = [
            "category", "name", "code", "phone", "fax", "address",
            "vehicle_capacity", "holiday_gift", "relationship_note", "note", "active",
        ]
        widgets = {
            "relationship_note": forms.Textarea(attrs={"rows": 2}),
            "note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = SalesSourceCategory.objects.filter(
            Q(active=True) | Q(pk=self.instance.category_id)
        ).order_by("system_behavior", "name")
        self.fields["category"].required = True
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        apply_mobile_keyboard_attrs(self)

    def save(self, commit=True):
        source = super().save(commit=False)
        source.source_type = source.category.system_behavior
        if commit:
            source.save()
            self.save_m2m()
        return source


class SalesSourceCategoryForm(forms.ModelForm):
    class Meta:
        model = SalesSourceCategory
        fields = ["name", "system_behavior", "active", "note"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        apply_mobile_keyboard_attrs(self)

    def clean_system_behavior(self):
        behavior = self.cleaned_data["system_behavior"]
        if (
            self.instance.pk
            and self.instance.system_behavior != behavior
            and self.instance.sources.exists()
        ):
            raise forms.ValidationError(
                "此分類已有通路使用，不能改變系統處理方式；請另建新分類後再調整通路。"
            )
        return behavior


class SalesSourceContactForm(forms.ModelForm):
    class Meta:
        model = SalesSourceContact
        fields = [
            "name", "relationship", "phone", "extension", "mobile", "email",
            "note", "active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        apply_mobile_keyboard_attrs(self)


SalesSourceContactFormSet = inlineformset_factory(
    SalesSource, SalesSourceContact, form=SalesSourceContactForm, extra=1, can_delete=True
)


def _brand_choices(current_value=""):
    brand_rows = list(
        VehicleBrand.objects.filter(active=True).select_related("parent")
    )
    brand_rows.sort(
        key=lambda brand: (
            brand.parent.display_order if brand.parent_id else brand.display_order,
            1 if brand.parent_id else 0,
            brand.display_order,
            brand.name.casefold(),
        )
    )
    brands = [(brand.name, brand.hierarchy_label) for brand in brand_rows]
    current = (current_value or "").strip()
    if current and current.casefold() not in {name.casefold() for name, _ in brands}:
        brands.append((current, current))
    return [("", "請選擇品牌"), *brands]


def _apply_brand_choice(form):
    current = getattr(form.instance, "brand", "")
    form.fields["brand"].choices = _brand_choices(current)
    form.fields["brand"].widget.attrs.update(
        {
            "class": "form-control",
            "data-searchable-select": "1",
            "data-search-placeholder": "輸入品牌名稱",
        }
    )


class VehicleBrandForm(forms.ModelForm):
    class Meta:
        model = VehicleBrand
        fields = ["name", "parent", "logo", "aliases", "display_order", "active", "note"]
        widgets = {
            "aliases": forms.Textarea(attrs={"rows": 3}),
            "note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        parent_queryset = VehicleBrand.objects.filter(parent__isnull=True)
        if self.instance.pk:
            parent_queryset = parent_queryset.exclude(pk=self.instance.pk)
            if self.instance.parent_id:
                parent_queryset = parent_queryset | VehicleBrand.objects.filter(
                    pk=self.instance.parent_id
                )
        self.fields["parent"].queryset = parent_queryset.distinct().order_by(
            "display_order", "name"
        )
        self.fields["parent"].empty_label = "獨立主品牌"
        if self.instance.pk:
            from .services.vehicle_brands import vehicle_brand_is_used

            if vehicle_brand_is_used(self.instance.name):
                self.fields["name"].disabled = True
                self.fields["name"].help_text = (
                    "此品牌已有車型或規則使用，名稱已鎖定；其他寫法請新增為別名。"
                )
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        duplicate = VehicleBrand.objects.filter(name__iexact=name)
        if self.instance.pk:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError("已有相同品牌；請編輯既有資料或新增別名。")
        return name

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if logo:
            validate_image_upload(logo)
        return logo

    def clean(self):
        cleaned = super().clean()
        parent = cleaned.get("parent")
        if parent and parent.parent_id:
            self.add_error("parent", "所屬品牌必須是主品牌，不能建立三層品牌。")
        if parent and self.instance.pk and self.instance.sub_brands.exists():
            self.add_error("parent", "此品牌已有子品牌，不能再改為其他品牌的子品牌。")
        aliases = re.split(r"[、,，\n\r]+", cleaned.get("aliases") or "")
        normalized = []
        seen = {(cleaned.get("name") or "").strip().casefold()}
        for alias in aliases:
            alias = alias.strip()
            key = alias.casefold()
            if alias and key not in seen:
                seen.add(key)
                normalized.append(alias)
        cleaned["aliases"] = "、".join(normalized)
        candidate_keys = {
            item.casefold()
            for item in [cleaned.get("name") or "", *normalized]
            if item
        }
        others = VehicleBrand.objects.all()
        if self.instance.pk:
            others = others.exclude(pk=self.instance.pk)
        for other in others:
            other_keys = {other.name.casefold()}
            other_keys.update(
                item.strip().casefold()
                for item in re.split(r"[、,，\n\r]+", other.aliases or "")
                if item.strip()
            )
            if candidate_keys & other_keys:
                self.add_error(
                    "aliases",
                    f"名稱或別名已由「{other.name}」使用，請避免重複。",
                )
                break
        return cleaned


class SalesSourceBrandPolicyForm(forms.ModelForm):
    brand = forms.ChoiceField(label="品牌")

    class Meta:
        model = SalesSourceBrandPolicy
        fields = [
            "brand", "cooperates", "commission_adjustment", "effective_from",
            "effective_to", "note",
        ]
        labels = {"commission_adjustment": "傭金加減額"}
        widgets = {"effective_from": DateInput(), "effective_to": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_brand_choice(self)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        apply_mobile_keyboard_attrs(self)


SalesSourceBrandPolicyFormSet = inlineformset_factory(
    SalesSource,
    SalesSourceBrandPolicy,
    form=SalesSourceBrandPolicyForm,
    extra=1,
    can_delete=True,
)


class InstallmentCompanyForm(forms.ModelForm):
    class Meta:
        model = InstallmentCompany
        fields = ["name", "customer_service_phone", "active", "note"]
        widgets = {"note": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        apply_mobile_keyboard_attrs(self)


class InstallmentPlanVersionForm(forms.ModelForm):
    class Meta:
        model = InstallmentPlanVersion
        fields = ["announced_on", "effective_from", "effective_to", "note", "active"]
        widgets = {
            "announced_on": DateInput(), "effective_from": DateInput(),
            "effective_to": DateInput(), "note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        apply_mobile_keyboard_attrs(self)


class InstallmentPlanOptionForm(forms.ModelForm):
    class Meta:
        model = InstallmentPlanOption
        fields = [
            "periods", "monthly_amount", "company", "opening_fee",
            "expected_disbursement_rate",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["company"].queryset = InstallmentCompany.objects.filter(
            Q(active=True) | Q(pk=self.instance.company_id)
        ).order_by("name")
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        apply_mobile_keyboard_attrs(self)


InstallmentPlanOptionFormSet = inlineformset_factory(
    InstallmentPlanVersion,
    InstallmentPlanOption,
    form=InstallmentPlanOptionForm,
    extra=1,
    can_delete=True,
)


class DealerVolumeBonusRuleForm(forms.ModelForm):
    brand = forms.ChoiceField(label="品牌")

    class Meta:
        model = DealerVolumeBonusRule
        fields = ["dealer", "brand", "starts_on", "ends_on", "active", "note"]
        widgets = {
            "starts_on": DateInput(), "ends_on": DateInput(),
            "note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_brand_choice(self)
        self.fields["dealer"].queryset = SalesSource.objects.filter(
            source_type=SalesSource.SourceType.DEALER, active=True
        ).order_by("name")
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        apply_mobile_keyboard_attrs(self)


class DealerVolumeBonusTierForm(forms.ModelForm):
    class Meta:
        model = DealerVolumeBonusTier
        fields = ["minimum_quantity", "bonus_per_vehicle"]


DealerVolumeBonusTierFormSet = inlineformset_factory(
    DealerVolumeBonusRule,
    DealerVolumeBonusTier,
    form=DealerVolumeBonusTierForm,
    extra=1,
    can_delete=True,
)


class DealerVolumeBonusSettlementForm(forms.ModelForm):
    class Meta:
        model = DealerVolumeBonusSettlement
        fields = ["actual_amount", "adjustment_reason"]
        widgets = {"adjustment_reason": forms.Textarea(attrs={"rows": 2})}


class DealerVolumeBonusAdjustmentForm(forms.Form):
    actual_amount = forms.DecimalField(
        label="修正後實際金額", max_digits=12, decimal_places=0, min_value=0
    )
    reason = forms.CharField(
        label="調整原因",
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="必填；此內容會永久保留在調整歷程。",
    )


class LegacyImportUploadForm(forms.ModelForm):
    class Meta:
        model = LegacyImportBatch
        fields = ["import_type", "source_file"]
        widgets = {
            "source_file": forms.ClearableFileInput(
                attrs={"accept": ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
            )
        }

    def clean_source_file(self):
        return validate_excel_upload(self.cleaned_data.get("source_file"))


class LegacyImportRowCorrectionForm(forms.Form):
    DECISION_CHOICES = (
        ("correct", "修正後匯入"),
        ("exclude", "不匯入此列"),
    )

    INVENTORY_FIELDS = (
        ("received_on", "進貨日期", "date", False),
        ("model_number", "車種型號", "text", True),
        ("identifier_raw", "引擎／車身號碼", "text", True),
        ("color", "顏色", "text", False),
        ("quantity", "數量（1 為可售、0 為歷史已售）", "integer", True),
        ("manufactured_year_month", "出廠年月", "year_month", False),
    )
    SALES_FIELDS = (
        ("vehicle_category", "車輛類別", "vehicle_category", True),
        ("transaction_type", "交易類型", "transaction_type", True),
        ("model_number", "車種型號", "text", True),
        ("identifier_raw", "引擎／車身號碼", "text", False),
        ("owner_name", "車主姓名", "text", True),
        ("color", "顏色", "text", False),
        ("registration_date", "實際領牌日期", "date", False),
        ("order_date", "訂單日期", "date", False),
        ("plate_number", "車牌號碼", "text", False),
        ("historical_received_price", "歷史收款價", "decimal", False),
        ("cash_received", "現金收款", "decimal", False),
        ("card_received", "刷卡收款", "decimal", False),
        ("payment_confirmed", "已確認收款", "boolean", False),
        ("dealer_name", "來源名稱", "text", False),
        ("installment_company", "分期公司", "text", False),
        ("installment_periods", "分期期數", "integer", False),
        ("owner_birth_date", "西元生日", "date", False),
        ("owner_id_number", "身分證字號", "text", False),
        ("owner_address", "戶籍地址", "textarea", False),
        ("owner_phone", "手機", "text", False),
        ("owner_email", "Email", "email", False),
        ("invoice_date", "發票日期", "date", False),
        ("balance_invoice_number", "尾款發票號碼", "text", False),
        ("subsidy_type", "補助方案", "text", False),
        ("subsidy_amount", "補助金額", "decimal", False),
        ("bank_name", "銀行名稱／分行", "text", False),
        ("remittance_account", "匯款帳戶", "text", False),
        ("trade_in_plate", "舊車牌照號碼", "text", False),
        ("old_owner_name", "舊車車主", "text", False),
        ("old_owner_id_number", "舊車主身分證", "text", False),
        ("old_vehicle_engine_number", "舊車引擎號碼", "text", False),
        ("old_vehicle_brand", "舊車廠牌", "text", False),
        ("old_vehicle_manufactured_year_month", "舊車出廠年月", "year_month", False),
        ("vehicle_control_account", "車控帳號", "text", False),
        ("battery_plan", "電池合約方案", "text", False),
        ("battery_account", "電池合約帳號", "text", False),
        ("standard_gift", "標配贈品", "textarea", False),
        ("company_gift", "公司實體贈品", "textarea", False),
        ("sales_category", "銷售方案分類", "text", False),
    )
    CHANNEL_FIELDS = (
        ("name", "車行／平台名稱", "text", True),
        ("contact_name", "聯絡窗口", "text", False),
        ("phone", "電話", "text", False),
        ("phone_2", "電話二", "text", False),
        ("extension", "分機", "text", False),
        ("mobile", "手機", "text", False),
        ("email", "Email", "text", False),
        ("fax", "傳真", "text", False),
        ("address", "地址", "textarea", False),
        ("vehicle_capacity", "停放容量", "integer", False),
        ("note", "備註", "textarea", False),
    )

    decision = forms.ChoiceField(
        label="這一列要怎麼處理？",
        choices=DECISION_CHOICES,
        widget=forms.RadioSelect,
    )
    reason = forms.CharField(
        label="修正／排除原因",
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "例如：Excel 重複列，保留較完整的一筆"}),
        help_text="此內容會連同處理人員與時間保留在稽核紀錄。",
    )

    def __init__(self, *args, row: LegacyImportRow, **kwargs):
        self.row = row
        super().__init__(*args, **kwargs)
        if row.sheet_name == "進貨":
            schema = self.INVENTORY_FIELDS
        elif row.sheet_name == "銷貨":
            schema = self.SALES_FIELDS
        else:
            schema = self.CHANNEL_FIELDS
        self.editable_keys = [key for key, *_ in schema]
        self.required_when_correcting = [key for key, _, _, required in schema if required]
        for key, label, kind, required in schema:
            display_label = f"{label}（修正時必填）" if required else label
            initial = row.mapped_data.get(key)
            if kind == "date":
                field = forms.DateField(
                    label=display_label,
                    required=False,
                    input_formats=["%Y-%m-%d"],
                    widget=forms.DateInput(attrs={"type": "date"}),
                )
            elif kind == "integer":
                field = forms.IntegerField(label=display_label, required=False, min_value=0)
            elif kind == "decimal":
                field = forms.DecimalField(label=display_label, required=False, max_digits=14, decimal_places=0)
            elif kind == "boolean":
                field = forms.BooleanField(label=display_label, required=False)
            elif kind == "vehicle_category":
                field = forms.ChoiceField(
                    label=display_label,
                    required=False,
                    choices=SalesOrder.VehicleCategory.choices,
                )
            elif kind == "transaction_type":
                field = forms.ChoiceField(
                    label=display_label,
                    required=False,
                    choices=SalesOrder.TransactionType.choices,
                )
            elif kind == "year_month":
                field = forms.RegexField(
                    label=display_label,
                    required=False,
                    regex=r"^\d{4}/(0[1-9]|1[0-2])$",
                    error_messages={"invalid": "請使用 YYYY/MM，例如 2026/08。"},
                )
            elif kind == "textarea":
                field = forms.CharField(label=display_label, required=False, widget=forms.Textarea(attrs={"rows": 2}))
            elif kind == "email":
                field = forms.CharField(
                    label=display_label,
                    required=False,
                )
            else:
                field = forms.CharField(label=display_label, required=False)
            if required:
                field.widget.attrs["data-required-when-correcting"] = "true"
            field.initial = initial
            self.fields[key] = field
        self.fields["decision"].initial = "exclude" if row.excluded else "correct"
        self.order_fields(["decision", *self.editable_keys, "reason"])

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") == "correct":
            for key in self.required_when_correcting:
                if cleaned.get(key) in (None, ""):
                    self.add_error(key, "選擇修正後匯入時，此欄位必須填寫。")
            owner_email = cleaned.get("owner_email")
            if owner_email:
                try:
                    validate_email(owner_email)
                except ValidationError:
                    self.add_error("owner_email", "請輸入有效的 Email，或將錯放的電話／地址清空。")
        return cleaned

    def cleaned_mapping(self):
        return {key: self.cleaned_data.get(key) for key in self.editable_keys}


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
        fields = [
            "accessory_product",
            "quantity",
            "line_type",
            "amount",
            "labor_fee",
            "note",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.original_accessory_product_id = self.instance.accessory_product_id
        self.fields["accessory_product"].queryset = AccessoryProduct.objects.filter(
            Q(active=True) | Q(pk=self.instance.accessory_product_id)
        ).order_by("name")
        self.fields["accessory_product"].label = "配件名稱"
        for field_name in (
            "accessory_product",
            "quantity",
            "line_type",
            "amount",
            "labor_fee",
        ):
            self.fields[field_name].required = False
        for field_name in ("amount", "labor_fee"):
            self.fields[field_name].widget.attrs["readonly"] = True
            self.fields[field_name].widget.attrs["tabindex"] = "-1"
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        apply_mobile_keyboard_attrs(self)
        if not self.is_bound and not self.instance.pk:
            self.fields["amount"].initial = None
            self.fields["labor_fee"].initial = None

    def clean(self):
        data = super().clean()
        product = data.get("accessory_product")
        if not product:
            if self.instance.pk and self.instance.name:
                return data
            data["DELETE"] = True
            self.cleaned_data["DELETE"] = True
            return data

        for field_name in ("quantity", "line_type"):
            if data.get(field_name) in (None, ""):
                self.add_error(field_name, "填寫配件名稱後，此欄位為必填。")
        if not self.instance.pk or product.pk != self.original_accessory_product_id:
            data["amount"] = product.sale_price
            data["labor_fee"] = product.labor_fee
            self.cleaned_data["amount"] = product.sale_price
            self.cleaned_data["labor_fee"] = product.labor_fee
            self.instance.name = product.name
        else:
            data["amount"] = self.instance.amount
            data["labor_fee"] = self.instance.labor_fee
            self.cleaned_data["amount"] = self.instance.amount
            self.cleaned_data["labor_fee"] = self.instance.labor_fee
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
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
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
        "manufactured_year_month",
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
            "manufactured_year_month",
            "condition_note",
            "condition_photo",
            "condition_resolution",
        ]
        widgets = {
            "received_on": DateInput(),
            "manufactured_year_month": forms.TextInput(
                attrs={"placeholder": "YYYY/MM", "inputmode": "numeric"}
            ),
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

    def clean_condition_photo(self):
        return validate_image_upload(self.cleaned_data.get("condition_photo"))


class VehicleModelMasterForm(forms.ModelForm):
    brand = forms.ChoiceField(label="品牌")
    existing_family = forms.ModelChoiceField(
        label="套用既有機種",
        queryset=VehicleModelFamily.objects.none(),
        required=False,
        empty_label="建立新機種",
        help_text="新增年式／規格時可直接選既有機種；選取後以既有品牌與機種名稱為準。",
    )
    model_number = forms.CharField(
        label="原廠型號",
        help_text="同一年式／規格可填多個原廠型號，請用頓號、逗號或換行分隔。",
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "例如：EV060L、EV062、EV062FL"}),
    )

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
            "motor_power_kw",
            "horsepower_hp",
            "electric_registration_class",
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
            "motor_power_kw": forms.NumberInput(
                attrs={"min": "0", "step": "0.01", "inputmode": "decimal"}
            ),
            "horsepower_hp": forms.NumberInput(
                attrs={"min": "0", "step": "0.01", "inputmode": "decimal"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_brand_choice(self)
        self.fields["existing_family"].queryset = VehicleModelFamily.objects.filter(
            active=True
        ).order_by("brand", "name")
        if self.instance.pk and self.instance.family_id:
            self.initial["existing_family"] = self.instance.family_id
            codes = list(
                self.instance.factory_model_codes.filter(active=True)
                .order_by("code")
                .values_list("code", flat=True)
            )
            if codes:
                self.initial["model_number"] = "、".join(codes)
        self.fields["brand"].required = False
        self.fields["name"].required = False
        self.fields["model_year"].required = True
        self.fields["model_number"].required = True
        self.fields["model_code"].required = True
        self.order_fields(
            [
                "existing_family",
                "brand",
                "energy_type",
                "name",
                "model_number",
                "model_year",
                "model_code",
                "displacement_cc",
                "motor_power_kw",
                "horsepower_hp",
                "electric_registration_class",
                "active",
            ]
        )
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        apply_mobile_keyboard_attrs(self)

    def clean(self):
        cleaned = super().clean()
        existing_family = cleaned.get("existing_family")
        if existing_family:
            cleaned["brand"] = existing_family.brand
            cleaned["name"] = existing_family.name
        brand = (cleaned.get("brand") or "").strip()
        name = (cleaned.get("name") or "").strip()
        if not existing_family and not brand:
            self.add_error("brand", "建立新機種時請選擇品牌。")
        if not existing_family and not name:
            self.add_error("name", "建立新機種時請填寫機種名稱。")
        model_numbers = tuple(
            dict.fromkeys(
                value.strip()
                for value in re.split(r"[、,，\n\r]+", cleaned.get("model_number") or "")
                if value.strip()
            )
        )
        cleaned["factory_model_numbers"] = model_numbers
        model_code = (cleaned.get("model_code") or "").strip()
        model_year = cleaned.get("model_year")
        duplicate = VehicleModel.objects.filter(
            brand__iexact=brand,
            name__iexact=name,
            model_year=model_year,
            model_code=model_code,
        )
        if self.instance.pk:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if (
            brand
            and name
            and model_numbers
            and model_year
            and model_code
            and duplicate.exists()
        ):
            raise forms.ValidationError(
                "此機種已有相同年份與型式的設定；請編輯既有設定並加入原廠型號。"
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
        if (
            cleaned.get("energy_type") == VehicleModel.EnergyType.ELECTRIC
            and not cleaned.get("electric_registration_class")
        ):
            self.add_error(
                "electric_registration_class",
                "電動車請依原廠認證選擇輕型或重型領牌級別。",
            )
        return cleaned

    def save(self, commit=True):
        vehicle_model = super().save(commit=False)
        model_numbers = self.cleaned_data.get("factory_model_numbers") or ()
        if model_numbers:
            vehicle_model.model_number = model_numbers[0]
        if not commit:
            return vehicle_model

        vehicle_model.save()
        self.save_m2m()
        factory_codes = []
        for code in model_numbers:
            normalized_code = normalize_legacy_master_value(code)
            factory_code, created = VehicleFactoryModelCode.objects.get_or_create(
                family=vehicle_model.family,
                normalized_code=normalized_code,
                defaults={"code": code, "active": True},
            )
            if not created and not factory_code.active:
                factory_code.active = True
                factory_code.save(update_fields=["active", "updated_at"])
            factory_codes.append(factory_code)
        vehicle_model.factory_model_codes.set(factory_codes)
        return vehicle_model


class LegacyVehicleModelLinkForm(forms.Form):
    vehicle_model = forms.ModelChoiceField(
        label="對應至既有車型",
        queryset=VehicleModel.objects.none(),
        empty_label="請選擇車型",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vehicle_model"].queryset = VehicleModel.objects.order_by(
            "brand", "name", "model_year", "model_number"
        )
        self.fields["vehicle_model"].widget.attrs.update(
            {
                "class": "form-control",
                "data-searchable-select": "1",
                "data-search-placeholder": "輸入品牌、車型、型號或年份",
            }
        )


class LegacySalesSourceLinkForm(forms.Form):
    sales_source = forms.ModelChoiceField(
        label="對應至既有通路",
        queryset=SalesSource.objects.none(),
        empty_label="請選擇車行或平台",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sales_source"].queryset = SalesSource.objects.order_by(
            "source_type", "name"
        )
        self.fields["sales_source"].widget.attrs.update(
            {
                "class": "form-control",
                "data-searchable-select": "1",
                "data-search-placeholder": "輸入車行或平台名稱",
            }
        )


class LegacyVehicleModelQuickCreateForm(forms.ModelForm):
    brand = forms.ChoiceField(label="品牌")
    colors = forms.CharField(
        label="已知顏色",
        required=False,
        help_text="可用逗號、頓號或換行分隔；系統會自動去除重複顏色。",
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "例如：白、灰、黑"}),
    )

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
            "motor_power_kw",
            "horsepower_hp",
            "electric_registration_class",
        ]
        labels = {
            "brand": "品牌",
            "energy_type": "能源別",
            "name": "機種",
            "model_number": "型號",
            "model_year": "年份",
            "model_code": "型式",
        }
        widgets = {
            "model_year": forms.NumberInput(
                attrs={"min": "1900", "max": "2200", "inputmode": "numeric"}
            ),
            "displacement_cc": forms.NumberInput(attrs={"inputmode": "numeric"}),
            "motor_power_kw": forms.NumberInput(
                attrs={"min": "0", "step": "0.01", "inputmode": "decimal"}
            ),
            "horsepower_hp": forms.NumberInput(
                attrs={"min": "0", "step": "0.01", "inputmode": "decimal"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_brand_choice(self)
        for field_name in ("brand", "energy_type", "name", "model_number", "model_year", "model_code"):
            self.fields[field_name].required = True
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        apply_mobile_keyboard_attrs(self)

    def cleaned_colors(self):
        raw = self.cleaned_data.get("colors", "")
        values = re.split(r"[、,，\n\r]+", raw)
        unique = []
        seen = set()
        for value in values:
            name = value.strip()
            key = name.casefold()
            if name and key not in seen:
                seen.add(key)
                unique.append(name)
        return unique

    def save(self, commit=True):
        vehicle_model = super().save(commit=commit)
        if commit:
            for color_name in self.cleaned_colors():
                VehicleColor.objects.get_or_create(
                    vehicle_model=vehicle_model,
                    name=color_name,
                    defaults={"active": True},
                )
        return vehicle_model


class LegacySalesSourceQuickCreateForm(forms.ModelForm):
    source_category = forms.ModelChoiceField(
        label="通路分類",
        queryset=SalesSourceCategory.objects.none(),
        required=False,
        help_text="例如：合作車行、網路平台、本店員工。",
    )
    new_category_name = forms.CharField(
        label="新分類名稱",
        required=False,
        max_length=80,
        help_text="現有分類不適用時才填寫，例如：本店員工。",
    )
    new_category_behavior = forms.ChoiceField(
        label="新分類的系統處理方式",
        required=False,
        choices=SalesSourceCategory.SystemBehavior.choices,
        help_text="本店來源不套車行傭金；合作車行與網路平台會進入各自對帳流程。",
    )

    class Meta:
        model = SalesSource
        fields = ["name", "address"]
        labels = {
            "name": "來源名稱",
            "address": "地址（選填）",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["source_category"].queryset = SalesSourceCategory.objects.filter(
            active=True
        ).order_by("system_behavior", "name")
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        apply_mobile_keyboard_attrs(self)

    def clean(self):
        cleaned = super().clean()
        selected = cleaned.get("source_category")
        new_name = (cleaned.get("new_category_name") or "").strip()
        behavior = cleaned.get("new_category_behavior")
        if not selected and not new_name:
            self.add_error("source_category", "請選擇既有分類，或建立一個新分類。")
        if new_name and not behavior:
            self.add_error("new_category_behavior", "建立新分類時請選擇系統處理方式。")
        existing = SalesSourceCategory.objects.filter(name__iexact=new_name).first()
        if existing and behavior and existing.system_behavior != behavior:
            self.add_error(
                "new_category_name",
                f"「{existing.name}」已存在，且系統處理方式為{existing.get_system_behavior_display()}。",
            )
        return cleaned

    @transaction.atomic
    def save(self, commit=True):
        source = super().save(commit=False)
        new_name = (self.cleaned_data.get("new_category_name") or "").strip()
        if new_name:
            category, _ = SalesSourceCategory.objects.get_or_create(
                name=new_name,
                defaults={
                    "system_behavior": self.cleaned_data["new_category_behavior"],
                    "active": True,
                },
            )
        else:
            category = self.cleaned_data["source_category"]
        source.category = category
        source.source_type = category.system_behavior
        if commit:
            source.save()
        return source


class VehiclePriceVersionForm(forms.ModelForm):
    class Meta:
        model = VehiclePriceVersion
        fields = [
            "suggested_price",
            "suggested_price_includes_registration",
            "cash_price",
            "announced_on",
            "effective_from",
            "effective_to",
            "source_note",
            "active",
        ]
        labels = {
            "suggested_price": "建議售價",
            "suggested_price_includes_registration": "此建議售價包含牌險",
            "cash_price": "現金價",
            "announced_on": "原廠／公司通知日期",
            "effective_from": "訂單生效日期",
            "effective_to": "結束日期（選填）",
            "source_note": "來源文件／調整原因",
        }
        help_texts = {
            "suggested_price": "原廠或公司公布的正式售價；是否包含牌險請依下方勾選。",
            "suggested_price_includes_registration": "若公告價格不含牌險，請取消勾選；系統不會自行加減價格。",
            "cash_price": "內部實際採用的現金車價；牌險依車型規則或正式單據另計。",
            "effective_from": "建立訂單時，系統依訂單日期套用當日有效版本。",
            "effective_to": "不填表示持續有效；價格調整時請新增版本，不要覆蓋舊版本。",
            "source_note": "例如營業通報月份、文件名稱或人工調整原因。",
        }
        widgets = {
            "suggested_price": forms.NumberInput(attrs={"inputmode": "numeric"}),
            "cash_price": forms.NumberInput(attrs={"inputmode": "numeric"}),
            "announced_on": DateInput(),
            "effective_from": DateInput(),
            "effective_to": DateInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        for field_name in (
            "suggested_price",
            "cash_price",
        ):
            if not self.is_bound and self.initial.get(field_name) in (None, 0):
                self.initial[field_name] = ""
        apply_mobile_keyboard_attrs(self)


class AccessoryProductForm(forms.ModelForm):
    class Meta:
        model = AccessoryProduct
        fields = ["name", "sale_price", "labor_fee", "cost", "active", "note"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        for field_name in ("sale_price", "labor_fee", "cost"):
            if not self.is_bound and self.initial.get(field_name) in (None, 0):
                self.initial[field_name] = ""
        apply_mobile_keyboard_attrs(self)


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


class VehicleIncentiveRuleForm(forms.ModelForm):
    class Meta:
        model = VehicleIncentiveRule
        fields = [
            "vehicle_model",
            "sales_bonus",
            "promotion_subsidy",
            "installment_interest_subsidy",
            "announced_on",
            "effective_from",
            "effective_to",
            "note",
            "active",
        ]
        widgets = {
            "sales_bonus": forms.NumberInput(attrs={"inputmode": "numeric"}),
            "promotion_subsidy": forms.NumberInput(attrs={"inputmode": "numeric"}),
            "installment_interest_subsidy": forms.NumberInput(
                attrs={"inputmode": "numeric"}
            ),
            "announced_on": DateInput(),
            "effective_from": DateInput(),
            "effective_to": DateInput(),
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vehicle_model"].queryset = VehicleModel.objects.filter(
            active=True
        ).order_by("brand", "name", "-model_year")
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        apply_mobile_keyboard_attrs(self)


class VehicleIncentiveInstallmentRateForm(forms.ModelForm):
    class Meta:
        model = VehicleIncentiveInstallmentRate
        fields = ["periods", "rate"]
        widgets = {
            "periods": forms.NumberInput(attrs={"min": "1", "inputmode": "numeric"}),
            "rate": forms.NumberInput(
                attrs={"min": "0", "max": "100", "step": "0.01", "inputmode": "decimal"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class BaseVehicleIncentiveInstallmentRateFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        periods_seen = {}
        for index, form in enumerate(self.forms, start=1):
            if not hasattr(form, "cleaned_data") or form.cleaned_data.get("DELETE"):
                rate = form.instance
                if (
                    hasattr(form, "cleaned_data")
                    and form.cleaned_data.get("DELETE")
                    and rate.pk
                    and rate.order_snapshots.exists()
                ):
                    raise forms.ValidationError(
                        f"第 {index} 列已被訂單採用，不能刪除；請新增新版規則。"
                    )
                continue
            periods = form.cleaned_data.get("periods")
            if not periods:
                continue
            if periods in periods_seen:
                form.add_error("periods", f"與第 {periods_seen[periods]} 列期數重複。")
            else:
                periods_seen[periods] = index


VehicleIncentiveInstallmentRateFormSet = inlineformset_factory(
    VehicleIncentiveRule,
    VehicleIncentiveInstallmentRate,
    form=VehicleIncentiveInstallmentRateForm,
    formset=BaseVehicleIncentiveInstallmentRateFormSet,
    extra=1,
    can_delete=True,
)


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
    @staticmethod
    def _is_used_color(color):
        return bool(
            color.pk
            and (
                color.vehicleinventory_set.exists()
                or color.salesorder_set.exists()
            )
        )

    def _should_delete_form(self, form):
        return super()._should_delete_form(form) and not self._is_used_color(
            form.instance
        )

    def clean(self):
        super().clean()
        names = {}
        for index, form in enumerate(self.forms, start=1):
            if not hasattr(form, "cleaned_data"):
                continue
            if form.cleaned_data.get("DELETE"):
                color = form.instance
                if self._is_used_color(color):
                    # 舊頁面或驗證失敗後可能殘留隱藏的 DELETE。已被歷史資料
                    # 使用的顏色一律安全轉為停用，避免把「取消啟用」誤判成刪除。
                    form.cleaned_data["DELETE"] = False
                    form.cleaned_data["active"] = False
                    form.instance.active = False
                    continue
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
            "incentive_rule",
            "incentive_installment_rate_rule",
            "incentive_installment_periods",
            "incentive_installment_rate",
            "incentive_registration_date",
            "incentive_locked_at",
            "incentive_locked_by",
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
            "vehicle_cost",
            "installment_fee_income",
            "installment_info",
            "payment_confirmed",
            "installment_transfer_confirmed",
            "card_fee_income",
            "card_fee_expense",
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
                    "sales_bonus",
                    "promotion_subsidy",
                    "installment_interest_subsidy",
                    "actual_disbursement",
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
            "card_principal",
            "card_fee_charged",
            "bank_card_fee",
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
        self.fields["payment_method"].widget = forms.Select(
            choices=[
                ("", "請選擇"),
                ("現金", "現金"),
                ("匯款", "匯款"),
                ("刷卡", "刷卡"),
                ("分期撥款", "分期撥款"),
                ("其他", "其他"),
            ]
        )
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

    def clean(self):
        cleaned = super().clean()
        card_values = (
            cleaned.get("card_principal") or Decimal("0"),
            cleaned.get("card_fee_charged") or Decimal("0"),
            cleaned.get("bank_card_fee") or Decimal("0"),
        )
        if any(card_values) and cleaned.get("payment_method") != "刷卡":
            self.add_error("payment_method", "填寫刷卡明細時，付款方式必須選擇「刷卡」。")
        return cleaned

    def clean_proof(self):
        return validate_document_upload(self.cleaned_data.get("proof"))


class DeliveryPaymentForm(forms.ModelForm):
    PAYMENT_METHOD_CHOICES = (
        ("", "請選擇"),
        ("現金", "現金"),
        ("匯款", "匯款"),
        ("刷卡", "刷卡"),
        ("其他", "其他"),
    )

    received_amount = forms.DecimalField(
        label="實收金額",
        max_digits=12,
        decimal_places=0,
        min_value=Decimal("0"),
    )
    received_on = forms.DateField(
        label="收款日期",
        required=False,
        widget=DateInput(),
    )
    payment_method = forms.ChoiceField(
        label="收款方式",
        choices=PAYMENT_METHOD_CHOICES,
        required=False,
    )
    confirmed = forms.BooleanField(
        label="確認此筆尾款已收妥",
        required=False,
    )

    class Meta:
        model = PaymentRecord
        fields = [
            "received_amount",
            "received_on",
            "payment_method",
            "receiving_account",
            "proof",
            "note",
            "confirmed",
        ]
        widgets = {
            "proof": forms.ClearableFileInput(
                attrs={"accept": "image/*,application/pdf"}
            ),
        }
        labels = {
            "receiving_account": "收款帳戶／末五碼",
            "proof": "收款證明",
            "note": "收款備註",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        expected = self.instance.expected_amount or Decimal("0")
        if not self.is_bound:
            if not self.instance.received_amount and expected > 0:
                self.initial["received_amount"] = expected
            if not self.instance.received_on:
                self.initial["received_on"] = timezone.localdate()
            allowed_methods = {value for value, _label in self.PAYMENT_METHOD_CHOICES}
            if self.instance.payment_method not in allowed_methods:
                self.initial["payment_method"] = ""
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        self.fields["confirmed"].widget.attrs["class"] = "form-check"
        self.fields["received_amount"].widget.attrs.update(
            {"inputmode": "numeric", "min": "0"}
        )
        apply_mobile_keyboard_attrs(self)


    def clean(self):
        cleaned = super().clean()
        received = cleaned.get("received_amount") or Decimal("0")
        expected = self.instance.expected_amount or Decimal("0")
        if received > 0:
            if not cleaned.get("received_on"):
                self.add_error("received_on", "已有實收金額時，請填寫收款日期。")
            if not cleaned.get("payment_method"):
                self.add_error("payment_method", "已有實收金額時，請選擇收款方式。")
        if cleaned.get("confirmed") and received < expected:
            shortage = expected - received
            self.add_error(
                "confirmed",
                f"尚差 {shortage:,.0f} 元，不可標記為已收清。",
            )
        return cleaned

    def clean_proof(self):
        return validate_document_upload(self.cleaned_data.get("proof"))

    def save(self, actor_name, commit=True):
        payment = super().save(commit=False)
        if payment.confirmed:
            payment.confirmed_by = actor_name
            payment.confirmed_at = timezone.now()
        else:
            payment.confirmed_by = ""
            payment.confirmed_at = None
        if commit:
            payment.save()
        return payment


class VehicleModelCommissionForm(forms.Form):
    base_dealer_commission = forms.DecimalField(
        label="車行基礎傭金",
        max_digits=12,
        decimal_places=0,
        min_value=Decimal("0"),
        help_text="合作車行銷售此車型時的預設傭金；特定車行的加減金額仍在通路資料維護。",
        widget=forms.NumberInput(attrs={"min": "0", "inputmode": "numeric"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["base_dealer_commission"].widget.attrs.setdefault(
            "class", "form-control"
        )
        apply_mobile_keyboard_attrs(self)


class ReconciliationRecordForm(forms.ModelForm):
    class Meta:
        model = PaymentRecord
        fields = [
            "received_amount",
            "received_on",
            "receiving_account",
            "confirmed",
            "note",
        ]
        widgets = {"received_on": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        self.fields["received_amount"].required = True
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
    manufactured_year_month = forms.RegexField(
        label="出廠年月",
        regex=r"^\d{4}/(0[1-9]|1[0-2])$",
        required=False,
        error_messages={"invalid": "請使用 YYYY/MM，例如 2026/08。"},
        widget=forms.TextInput(
            attrs={"placeholder": "YYYY/MM", "inputmode": "numeric"}
        ),
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
            normalized_identifier = normalize_vehicle_identifier(identifier)
            active_forms.append((form, normalized_identifier))
            if normalized_identifier in identifiers:
                form.add_error(
                    "identifier",
                    f"與第 {identifiers[normalized_identifier]} 列重複（空格與連字號不影響比對）。",
                )
            else:
                identifiers[normalized_identifier] = index
        if not active_forms:
            raise forms.ValidationError("請至少填寫一台車輛。")
        existing = set(
            VehicleInventory.objects.filter(
                Q(normalized_engine_number__in=identifiers)
                | Q(normalized_frame_number__in=identifiers)
            ).values_list("normalized_engine_number", "normalized_frame_number")
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

    def clean_signed_contract(self):
        return validate_document_upload(self.cleaned_data.get("signed_contract"))


class PrivacyConsentForm(forms.ModelForm):
    class Meta:
        model = SalesOrder
        fields = ["privacy_consent"]
        widgets = {
            "privacy_consent": forms.ClearableFileInput(
                attrs={"accept": "image/*,application/pdf", "capture": "environment"}
            )
        }

    def clean_privacy_consent(self):
        return validate_document_upload(self.cleaned_data.get("privacy_consent"))


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

    def clean(self):
        cleaned = super().clean()
        registration_date = cleaned.get("registration_date")
        model = self.instance.vehicle_model
        has_rate_basis = bool(
            model.displacement_cc
            if model.energy_type == VehicleModel.EnergyType.GAS
            else model.electric_registration_class
            if model.energy_type == VehicleModel.EnergyType.ELECTRIC
            else False
        )
        if registration_date and has_rate_basis:
            try:
                self._registration_result = calculate_vehicle_registration_fee(
                    model,
                    registration_date,
                    self.instance.compulsory_insurance_period,
                )
            except UnsupportedRegistrationFee as exc:
                self.add_error("registration_date", str(exc))
        return cleaned

    def save(self, commit=True):
        order = super().save(commit=False)
        model = order.vehicle_model
        if order.registration_date and hasattr(self, "_registration_result"):
            result = self._registration_result
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


class DeliveryCompletionForm(forms.Form):
    VEHICLE_CONDITION_NORMAL = "正常"
    VEHICLE_CONDITION_DAMAGED = "發現刮傷或損壞"
    VEHICLE_CONDITION_OTHER = "其他狀況"
    VEHICLE_CONDITION_CHOICES = (
        (VEHICLE_CONDITION_NORMAL, "正常"),
        (VEHICLE_CONDITION_DAMAGED, "發現刮傷或損壞"),
        (VEHICLE_CONDITION_OTHER, "其他狀況"),
    )

    delivery_method = forms.ChoiceField(
        label="交付方式", choices=SalesOrder.DeliveryMethod.choices
    )
    delivery_destination = forms.CharField(
        label="送達地點／託運目的地", max_length=250, required=False
    )
    delivered_at = forms.DateTimeField(
        label="實際交付時間",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )
    recipient_name = forms.CharField(label="實際收車人", max_length=160)
    recipient_phone = forms.CharField(label="收車人電話", max_length=30)
    carrier_name = forms.CharField(label="託運公司", max_length=160, required=False)
    handover_location = forms.CharField(label="實際交付地點", max_length=250)
    # 使用 CharField 搭配 RadioSelect，而不是嚴格 ChoiceField：新版畫面只會
    # 顯示快選值，但尚未重新載入的舊版 PWA 仍可送出原本的自由文字。
    vehicle_condition_note = forms.CharField(
        label="交付車況",
        widget=forms.RadioSelect(choices=VEHICLE_CONDITION_CHOICES),
    )
    damage_note = forms.CharField(
        label="刮傷／損壞說明",
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 2, "placeholder": "例如：右側車殼刮痕約 3 公分"}
        ),
    )
    note = forms.CharField(
        label="交付備註／其他狀況說明",
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 2, "placeholder": "可記錄既有痕跡、客戶交代或其他特殊情況"}
        ),
    )
    condition_checked = forms.BooleanField(label="已核對車況")
    documents_checked = forms.BooleanField(label="已核對交付文件")
    keys_checked = forms.BooleanField(label="已核對鑰匙")
    accessories_checked = forms.BooleanField(label="已核對配件與贈品")
    handover_photo = forms.ImageField(label="交付照片", required=False)

    def __init__(self, order, *args, **kwargs):
        self.order = order
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial.update(
                {
                    "delivery_method": order.delivery_method,
                    "delivery_destination": order.delivery_destination,
                    "delivered_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
                    "recipient_name": order.owner_name,
                    "recipient_phone": order.owner_phone,
                    "handover_location": order.delivery_destination
                    or "馭盛國際有限公司",
                }
            )
        for field_name, field in self.fields.items():
            if field_name == "vehicle_condition_note":
                continue
            field.widget.attrs.setdefault("class", "form-control")
        for field_name in (
            "condition_checked",
            "documents_checked",
            "keys_checked",
            "accessories_checked",
        ):
            self.fields[field_name].widget.attrs["class"] = "form-check"
        self.fields["vehicle_condition_note"].widget.attrs[
            "class"
        ] = "delivery-condition-options"
        self.fields["recipient_phone"].widget.attrs["inputmode"] = "tel"

    def clean(self):
        data = super().clean()
        method = data.get("delivery_method")
        if method in {
            SalesOrder.DeliveryMethod.DIRECT_DELIVERY,
            SalesOrder.DeliveryMethod.CARRIER,
        } and not (data.get("delivery_destination") or "").strip():
            self.add_error("delivery_destination", "此交付方式必須填寫目的地。")
        if (
            method == SalesOrder.DeliveryMethod.CARRIER
            and not (data.get("carrier_name") or "").strip()
        ):
            self.add_error("carrier_name", "委託託運時必須填寫託運公司。")
        vehicle_condition = data.get("vehicle_condition_note")
        known_conditions = {value for value, _label in self.VEHICLE_CONDITION_CHOICES}
        # 舊版畫面會送出自由文字與 damage_found checkbox；新版則直接由
        # 「發現刮傷或損壞」快選推導，避免使用者重複判斷同一件事。
        damage_found = vehicle_condition == self.VEHICLE_CONDITION_DAMAGED or (
            vehicle_condition not in known_conditions
            and bool(self.data.get("damage_found"))
        )
        data["damage_found"] = damage_found
        if damage_found and not (data.get("damage_note") or "").strip():
            self.add_error("damage_note", "發現刮傷或損壞時必須填寫說明。")
        if vehicle_condition == self.VEHICLE_CONDITION_OTHER and not (
            data.get("note") or ""
        ).strip():
            self.add_error("note", "選擇其他狀況時，請在交付備註補充說明。")
        return data

    def clean_handover_photo(self):
        return validate_image_upload(self.cleaned_data.get("handover_photo"))

    @transaction.atomic
    def save(self, actor_name):
        order = SalesOrder.objects.select_for_update().get(pk=self.order.pk)
        order.delivery_method = self.cleaned_data["delivery_method"]
        order.delivery_destination = self.cleaned_data["delivery_destination"]
        order.save(update_fields=["delivery_method", "delivery_destination", "updated_at"])
        record = DeliveryRecord(
            order=order,
            recipient_name=self.cleaned_data["recipient_name"],
            recipient_phone=self.cleaned_data["recipient_phone"],
            carrier_name=self.cleaned_data["carrier_name"],
            handover_location=self.cleaned_data["handover_location"],
            vehicle_condition_note=self.cleaned_data["vehicle_condition_note"],
            condition_checked=self.cleaned_data["condition_checked"],
            documents_checked=self.cleaned_data["documents_checked"],
            keys_checked=self.cleaned_data["keys_checked"],
            accessories_checked=self.cleaned_data["accessories_checked"],
            # 尾款由交付頁的獨立收款區塊確認；合作車行可先交車，
            # 因此這裡記錄的是「已核對收款狀態」而非「已全數收清」。
            payment_checked=True,
            damage_found=self.cleaned_data["damage_found"],
            damage_note=self.cleaned_data["damage_note"],
            handover_photo=self.cleaned_data.get("handover_photo"),
            note=self.cleaned_data["note"],
            completed_by=actor_name,
        )
        record.full_clean()
        record.save()
        order.complete_delivery(self.cleaned_data["delivered_at"], actor_name)
        return order, record


class CancellationRequestForm(forms.Form):
    reason = forms.CharField(label="取消原因", max_length=250)
    note = forms.CharField(
        label="取消說明", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class RefundCompletionForm(forms.Form):
    amount = forms.DecimalField(
        label="退款金額", max_digits=12, decimal_places=0, min_value=0
    )
    completed_on = forms.DateField(label="退款完成日期", widget=DateInput())
    method = forms.ChoiceField(label="退款方式", choices=SalesOrder.PaymentMethod.choices)
    reference = forms.CharField(
        label="退款帳號／交易資訊", max_length=250, required=False
    )
    proof = forms.FileField(label="退款證明", required=False)

    def __init__(self, order, *args, **kwargs):
        self.order = order
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial.update(
                {"amount": order.deposit_amount, "completed_on": timezone.localdate()}
            )
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        self.fields["amount"].widget.attrs["inputmode"] = "numeric"

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount != self.order.deposit_amount:
            raise forms.ValidationError(
                f"訂金必須全數退還，請填寫 {self.order.deposit_amount:,.0f} 元。"
            )
        return amount

    def clean_proof(self):
        return validate_document_upload(self.cleaned_data.get("proof"))


class BusinessHolidayForm(forms.ModelForm):
    class Meta:
        model = BusinessHoliday
        fields = ["date", "name", "active"]
        widgets = {"date": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class BrandRegistrationFeeRuleForm(forms.ModelForm):
    brand = forms.ChoiceField(label="品牌")

    class Meta:
        model = BrandRegistrationFeeRule
        fields = [
            "brand",
            "energy_type",
            "electric_registration_class",
            "calculation_type",
            "min_cc",
            "max_cc",
            "fixed_total",
            "fixed_registration_fee",
            "fixed_compulsory_insurance_fee",
            "insurance_period_years",
            "effective_from",
            "effective_to",
            "active",
            "note",
        ]
        widgets = {
            "effective_from": DateInput(),
            "effective_to": DateInput(),
            "note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_brand_choice(self)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        for name in (
            "min_cc",
            "max_cc",
            "fixed_total",
            "fixed_registration_fee",
            "fixed_compulsory_insurance_fee",
            "insurance_period_years",
        ):
            self.fields[name].widget.attrs["inputmode"] = "numeric"
        self.fields["min_cc"].required = False
        self.fields["max_cc"].required = False
        self.fields["fixed_total"].required = False
        self.fields["electric_registration_class"].required = False
        self.fields["fixed_registration_fee"].required = False
        self.fields["fixed_compulsory_insurance_fee"].required = False
        self.fields["effective_to"].required = False
        self.fields["note"].required = False

    def clean_fixed_total(self):
        return self.cleaned_data.get("fixed_total") or 0

    def clean_fixed_registration_fee(self):
        return self.cleaned_data.get("fixed_registration_fee") or 0

    def clean_fixed_compulsory_insurance_fee(self):
        return self.cleaned_data.get("fixed_compulsory_insurance_fee") or 0


class PositionedPrintTemplateForm(forms.ModelForm):
    class Meta:
        model = PositionedPrintTemplate
        fields = [
            "name",
            "document_type",
            "version",
            "paper_size",
            "orientation",
            "width_mm",
            "height_mm",
            "background_file",
            "printer_offset_x_mm",
            "printer_offset_y_mm",
            "active",
            "note",
        ]
        widgets = {"note": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        self.fields["background_file"].widget.attrs["accept"] = ".xlsx,.xlsm,.pdf,.jpg,.jpeg,.png,.webp"

    def clean_background_file(self):
        return validate_template_background(self.cleaned_data.get("background_file"))


class PositionedPrintFieldForm(forms.ModelForm):
    field_key = forms.ChoiceField(label="資料欄位", choices=PRINT_FIELD_CHOICES)

    class Meta:
        model = PositionedPrintField
        fields = [
            "field_key",
            "label",
            "x_mm",
            "y_mm",
            "width_mm",
            "font_size",
            "alignment",
            "prefix",
            "suffix",
            "sort_order",
            "active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        for name in ("x_mm", "y_mm", "width_mm", "font_size", "sort_order"):
            self.fields[name].widget.attrs["inputmode"] = "decimal"


PositionedPrintFieldFormSet = inlineformset_factory(
    PositionedPrintTemplate,
    PositionedPrintField,
    form=PositionedPrintFieldForm,
    extra=1,
    can_delete=True,
)


class DiscountRequestForm(forms.Form):
    amount = forms.DecimalField(label="折扣金額", max_digits=12, decimal_places=0, min_value=1)
    reason = forms.CharField(label="申請原因", max_length=250, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        self.fields["amount"].widget.attrs["inputmode"] = "numeric"


class DiscountDecisionForm(forms.Form):
    decision = forms.ChoiceField(
        label="處理結果",
        choices=(("approve", "核准並套用"), ("reject", "不採用")),
        widget=forms.RadioSelect,
    )
    note = forms.CharField(label="確認備註", required=False, max_length=250)


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
            in RegistrationDocument.retired_document_types()
        ):
            self.add_error("document_type", "此文件項目已取消，不需再上傳。")
        if (
            data.get("document_type")
            == RegistrationDocument.DocumentType.OTHER_INSURANCE
            and not data.get("name")
        ):
            self.add_error("name", "新增其他保險單時必須填寫保險名稱。")
        return data

    def clean_file(self):
        return validate_document_upload(self.cleaned_data.get("file"))


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
        return validate_subsidy_upload(self.cleaned_data.get("file"))


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


class SubsidyItemForm(forms.ModelForm):
    class Meta:
        model = SubsidyItem
        fields = ["category", "item_name", "expected_amount", "applied_on", "status", "note"]
        widgets = {"applied_on": DateInput()}


SubsidyItemFormSet = inlineformset_factory(
    SalesOrder,
    SubsidyItem,
    form=SubsidyItemForm,
    extra=1,
    can_delete=True,
)
