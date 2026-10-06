"""店內與車行共用下單表單；僅依帳號能力限制進階欄位。"""
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from sales.forms import SalesOrderForm
from sales.models import SalesOrder
from sales.services.installment_plan import resolve_installment_plan_version
from sales.services.order_intake import account_profile, can_edit_finance, can_receive
from sales.services.upload_validation import validate_document_upload


# 訂金是客人當場付的款項，所有可建立訂單的帳號（含接待模式與合作車行）都要能填寫，
# 因此不列入財務欄位；其他財務欄位仍依原權限。
DEPOSIT_FIELDS = ("deposit_amount", "deposit_date", "deposit_method")

FINANCE_FIELDS = (
    "registration_manual", "registration_adjustment_reason",
    "commission_recipient", "assign_commission_to_other", "vehicle_price", "vehicle_price_adjustment_reason",
    "registration_date", "compulsory_insurance_period",
    "registration_plate_fee", "registration_license_fee", "registration_inspection_fee", "road_maintenance_fee",
    "license_tax_fee", "compulsory_insurance_fee", "plate_selection_fee", "lien_registration_fee",
    "registration_calculated_total", "plate_insurance_fee", "installment_opening_fee", "installment_monthly",
    "is_trade_in_subsidy",
)

PRICING_FIELDS = {
    "vehicle_price", "vehicle_price_adjustment_reason", "installment_opening_fee", "installment_monthly",
    "plate_insurance_fee", "plate_selection_fee", "lien_registration_fee",
}


class IntakeOrderForm(SalesOrderForm):
    accept_by_me = forms.BooleanField(label="由我接單（建立後直接進入待配車）", required=False)
    catalog_selection = forms.CharField(required=False, widget=forms.HiddenInput, max_length=4096)
    assisted_company_confirmed = forms.BooleanField(label="我已確認這是實際銷售車行，訂購單及個資同意書使用上述公司資料", required=False)
    assisted_company_revision = forms.IntegerField(required=False, min_value=0, widget=forms.HiddenInput)
    # 總價優惠：下單時填寫即直接核定（電子簽署的訂購單須為最終內容），規則同金額收支頁的折扣。
    intake_discount_mode = forms.ChoiceField(
        label="優惠方式", choices=[("amount", "減少金額"), ("rate", "折數")], required=False, initial="amount",
        widget=forms.RadioSelect,
    )
    intake_discount_amount = forms.DecimalField(
        label="總價減少金額（元）", max_digits=12, decimal_places=0, min_value=1, required=False,
    )
    intake_discount_rate = forms.DecimalField(
        label="折數（9 為九折、9.5 為九五折）", max_digits=5, decimal_places=2,
        min_value=Decimal("0.01"), max_value=Decimal("9.99"), required=False,
    )
    intake_discount_reason = forms.CharField(
        label="優惠原因", max_length=250, required=False, widget=forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
    )

    class Meta(SalesOrderForm.Meta):
        fields = [*SalesOrderForm.Meta.fields, "trade_in_intent"]

    def __init__(self, *args, user, reception=False, **kwargs):
        supplied_initial = kwargs.get("initial") or {}
        self.intake_user = user
        self.finance_editable = not reception and can_edit_finance(user)
        from sales.access.services import AccessPolicy
        self.pricing_editable = AccessPolicy(user).screen("order_pricing", "operate") or self.finance_editable
        profile = account_profile(user)
        self.dealer = bool(profile and profile.kind == "dealer")
        super().__init__(*args, **kwargs)
        self.assisted_company = None
        self.assisted_companies = {}
        if not self.dealer:
            from sales.models import PrintCompany
            from sales.services.print_company import FIELDS
            self.fields["source_type"].label = "開單方式／銷售來源"
            self.fields["source_type"].choices = [
                (key, "代合作車行開單" if key == "dealer" else label)
                for key, label in self.fields["source_type"].choices
            ]
            self.assisted_companies = {str(c.source_id): {**{key: getattr(c, key) for key in FIELDS}, "revision": c.revision}
                for c in PrintCompany.objects.filter(source__active=True, source__source_type="dealer")}
        self.fields["trade_in_intent"].required = False
        self.fields["installment_custom"].disabled = not self.pricing_editable
        if not self.pricing_editable:
            self.initial["installment_custom"] = False
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
            if not self.pricing_editable:
                for name in ("installment_company", "installment_periods"):
                    self.fields[name].widget.attrs["readonly"] = True
            for name in FINANCE_FIELDS:
                if self.pricing_editable and name in PRICING_FIELDS:
                    continue
                field = self.fields[name]
                field.disabled = True
                field.required = False
                self.initial[name] = None
            self.initial["compulsory_insurance_period"] = 1
        self.fields["deposit_amount"].required = False
        self.fields["deposit_amount"].widget.attrs.update(min="0", placeholder="無訂金填 0")
        self.fields["intake_discount_mode"].widget.attrs = {"class": "discount-mode__input"}
        self.fields["intake_discount_amount"].widget.attrs.update(inputmode="numeric", min="1", placeholder="例如 2000")
        self.fields["intake_discount_rate"].widget.attrs.update(inputmode="decimal", step="0.01", placeholder="例如 9.5")
        self.fields["intake_discount_reason"].widget.attrs.update(placeholder="例如：老客戶回購、展示車")
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
        if data.get("deposit_amount") is None and "deposit_amount" not in self.errors:
            data["deposit_amount"] = Decimal("0")
        elif data.get("deposit_amount") is not None and data["deposit_amount"] < 0:
            self.add_error("deposit_amount", "訂金不可小於零。")
        self._clean_intake_discount(data)
        # 鎖住的財務欄位即使被偽造送出也一律不採用：空值交回模型預設，避免寫入 null。
        for name in FINANCE_FIELDS:
            if name in self.fields and self.fields[name].disabled and data.get(name) is None:
                data.pop(name, None)
        if not self.dealer and data.get("source_type") == "dealer" and data.get("source"):
            from sales.models import PrintCompany
            from sales.services.print_company import validate_header, company_data
            companies = PrintCompany.objects.filter(source=data["source"])
            if transaction.get_connection().in_atomic_block:
                companies = companies.select_for_update()
            company = companies.first()
            if not company:
                self.add_error("assisted_company_confirmed", "此車行尚未設定訂購單公司資料，請 admin 完成設定後再代開。")
            else:
                try:
                    validate_header(company_data(company))
                except ValidationError:
                    self.add_error("assisted_company_confirmed", "此車行公司資料不完整，請 admin 完成公司名稱、地址、電話及統編。")
                if not data.get("assisted_company_confirmed"):
                    self.add_error("assisted_company_confirmed", "請確認代開車行與訂購文件公司資料。")
                if data.get("assisted_company_revision") != company.revision:
                    self.add_error("assisted_company_confirmed", "公司資料已更新或尚未載入，請重新確認畫面上的公司資料後再送出。")
                self.assisted_company = company
        data["trade_in_intent"] = data.get("trade_in_intent") or "unknown"
        data["is_trade_in_subsidy"] = data["trade_in_intent"] == "yes"
        if data["trade_in_intent"] != "yes":
            data["old_owner_same_as_owner"] = False
        elif data.get("old_owner_same_as_owner"):
            data["old_owner_name"] = data.get("owner_name", "")
            data["old_owner_id_number"] = data.get("owner_id_number", "")
        model = data.get("vehicle_model")
        if model and model.energy_type != "gas" and not data.get("owner_email"):
            self.add_error("owner_email", "電動車需填寫車主 Email。")
        if not self.pricing_editable and model and data.get("payment_type") == SalesOrder.PaymentType.INSTALLMENT:
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
                        or (not self.pricing_editable and data.get("payment_type") != selected["payment_type"])
                        or (not self.pricing_editable and selected["payment_type"] == "installment" and
                            (data.get("installment_company") != selected["company"] or data.get("installment_periods") != selected["periods"]))):
                    raise ValidationError(CHANGE_MESSAGE)
            except ValidationError as exc:
                self.add_error("catalog_selection", exc)
        return data


    def _clean_intake_discount(self, data):
        mode = data.get("intake_discount_mode") or "amount"
        data["intake_discount_mode"] = mode
        # 只保留所選方式的數值，避免切換方式後殘留的另一欄被當成優惠。
        if mode == "rate":
            data["intake_discount_amount"] = None
        else:
            data["intake_discount_rate"] = None
        data["intake_discount_reason"] = (data.get("intake_discount_reason") or "").strip()
        if (data.get("intake_discount_amount") or data.get("intake_discount_rate")) and not data["intake_discount_reason"]:
            self.add_error("intake_discount_reason", "有總價優惠時，請填寫優惠原因。")


def validated_intake_uploads(files):
    if sum(upload.size for _, values in files.lists() for upload in values) > 35 * 1024 * 1024:
        raise ValidationError("同次上傳含證件合計最多 35 MB；請分批暫存並重新開啟草稿後續傳。")
    uploads = [("installment", f) for f in files.getlist("installment_document")] + [("supplement", f) for f in files.getlist("supplement_documents")]
    for kind in ("owner_bankbook", "old_id_front", "old_id_back", "old_bankbook"):
        if len(files.getlist(kind)) > 1:
            raise ValidationError("同類證件每次限上傳一份。")
        uploads.extend((kind, f) for f in files.getlist(kind))
    if len(files.getlist("installment_document")) > 1 or len(files.getlist("supplement_documents")) > 10:
        raise ValidationError("分期表限 1 個檔案，補充附件最多 10 個。")
    for _, upload in uploads:
        validate_document_upload(upload)
    return uploads
