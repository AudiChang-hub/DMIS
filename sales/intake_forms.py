"""店內與車行共用下單表單；僅依帳號能力限制進階欄位。"""
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from sales.forms import SalesOrderForm
from sales.models import SalesOrder
from sales.services.installment_plan import resolve_installment_plan_version
from sales.services.order_intake import account_profile, can_edit_finance, can_receive
from sales.services.upload_validation import validate_document_upload


FINANCE_FIELDS = (
    "registration_manual", "registration_adjustment_reason",
    "commission_recipient", "assign_commission_to_other", "vehicle_price", "vehicle_price_adjustment_reason",
    "deposit_amount", "deposit_date", "deposit_method", "registration_date", "compulsory_insurance_period",
    "registration_plate_fee", "registration_license_fee", "registration_inspection_fee", "road_maintenance_fee",
    "license_tax_fee", "compulsory_insurance_fee", "plate_selection_fee", "lien_registration_fee",
    "registration_calculated_total", "plate_insurance_fee", "installment_opening_fee", "installment_monthly",
    "is_trade_in_subsidy", "old_owner_same_as_owner",
)


class IntakeOrderForm(SalesOrderForm):
    accept_by_me = forms.BooleanField(label="由我接單（建立後直接進入待配車）", required=False)
    catalog_selection = forms.CharField(required=False, widget=forms.HiddenInput, max_length=4096)

    class Meta(SalesOrderForm.Meta):
        fields = [*SalesOrderForm.Meta.fields, "trade_in_intent"]

    def __init__(self, *args, user, reception=False, **kwargs):
        supplied_initial = kwargs.get("initial") or {}
        self.intake_user = user
        self.finance_editable = not reception and can_edit_finance(user)
        profile = account_profile(user)
        self.dealer = bool(profile and profile.kind == "dealer")
        super().__init__(*args, **kwargs)
        self.fields["trade_in_intent"].required = False
        self.fields["accept_by_me"].disabled = reception or not can_receive(user)
        if profile and profile.source_id:
            from sales.models import SalesSource
            for key, value in (("source_type", profile.source.source_type), ("source", profile.source_id)):
                if self.dealer or (not self.is_bound and key not in supplied_initial):
                    self.initial[key] = value
                if self.dealer:
                    self.fields[key].disabled = True
            if self.dealer:
                self.fields["source"].queryset = SalesSource.objects.filter(pk=profile.source_id, active=True)
        if not self.finance_editable:
            self.fields["commission_recipient"].queryset = self.fields["commission_recipient"].queryset.none()
            for name in ("installment_company", "installment_periods"):
                self.fields[name].widget.attrs["readonly"] = True
            for name in FINANCE_FIELDS:
                field = self.fields[name]
                field.disabled = True
                field.required = False
                self.initial[name] = 0 if name == "deposit_amount" else None
            self.initial["compulsory_insurance_period"] = 1
            self.initial["old_owner_same_as_owner"] = True
        self.catalog_summary = None
        token = self.data.get("catalog_selection") if self.is_bound else self.initial.get("catalog_selection")
        if token:
            from sales.services.catalog_selection import read_selection
            try:
                self.catalog_summary = read_selection(token)
                if not self.is_bound:
                    self.initial["installment_monthly"] = self.catalog_summary["monthly"]
                    self.initial["installment_opening_fee"] = self.catalog_summary["opening_fee"]
            except ValidationError:
                pass  # 保留草稿內容；送出時明確提示重新確認，不在載入時換價。

    def clean(self):
        data = super().clean()
        data["trade_in_intent"] = data.get("trade_in_intent") or "unknown"
        model = data.get("vehicle_model")
        if model and model.energy_type != "gas" and not data.get("owner_email"):
            self.add_error("owner_email", "電動車需填寫車主 Email。")
        if not self.finance_editable and model and data.get("payment_type") == SalesOrder.PaymentType.INSTALLMENT:
            version = resolve_installment_plan_version(model.pk, timezone.localdate())
            option = version.options.select_related("company").filter(periods=data.get("installment_periods"), company__name=data.get("installment_company"), company__active=True).first() if version else None
            if not option:
                self.add_error("installment_periods", "請選擇此車型目前有效的分期方案；無方案請洽店內人員。")
            else:
                data["installment_monthly"] = option.monthly_amount
                data["installment_opening_fee"] = option.opening_fee
        if data.get("catalog_selection"):
            from sales.services.catalog_selection import validate_selection, CHANGE_MESSAGE
            try:
                selected = validate_selection(data["catalog_selection"])
                color = data.get("color")
                if (not model or not color or model.pk != selected["model"] or color.pk != selected["color"]
                        or data.get("payment_type") != selected["payment_type"]
                        or (selected["payment_type"] == "installment" and
                            (data.get("installment_company") != selected["company"] or data.get("installment_periods") != selected["periods"]))):
                    raise ValidationError(CHANGE_MESSAGE)
            except ValidationError as exc:
                self.add_error("catalog_selection", exc)
        return data


def validated_intake_uploads(files):
    if sum(upload.size for _, values in files.lists() for upload in values) > 35 * 1024 * 1024:
        raise ValidationError("同次上傳含證件合計最多 35 MB；請分批暫存並重新開啟草稿後續傳。")
    uploads = [("installment", f) for f in files.getlist("installment_document")] + [("supplement", f) for f in files.getlist("supplement_documents")]
    if len(files.getlist("installment_document")) > 1 or len(files.getlist("supplement_documents")) > 10:
        raise ValidationError("分期表限 1 個檔案，補充附件最多 10 個。")
    for _, upload in uploads:
        validate_document_upload(upload)
    return uploads
