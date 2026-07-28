import uuid

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="建立時間")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新時間")

    class Meta:
        abstract = True


class Store(TimeStampedModel):
    name = models.CharField("門市名稱", max_length=100, unique=True)
    code = models.CharField("門市代碼", max_length=20, unique=True)
    active = models.BooleanField("啟用中", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "門市"
        verbose_name_plural = "門市"

    def __str__(self):
        return self.name


class SalesSource(TimeStampedModel):
    class SourceType(models.TextChoices):
        DEALER = "dealer", "合作車行"
        PLATFORM = "platform", "網路平台"

    name = models.CharField("來源名稱", max_length=120)
    source_type = models.CharField("來源類型", max_length=20, choices=SourceType.choices)
    active = models.BooleanField("啟用中", default=True)

    class Meta:
        ordering = ["source_type", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_type", "name"], name="unique_sales_source_name"
            )
        ]
        verbose_name = "訂單來源"
        verbose_name_plural = "訂單來源"

    def __str__(self):
        return self.name


class VehicleModel(TimeStampedModel):
    class EnergyType(models.TextChoices):
        GAS = "gas", "油車"
        ELECTRIC = "electric", "電動車"

    brand = models.CharField("廠牌", max_length=80)
    name = models.CharField("車型", max_length=120)
    energy_type = models.CharField("動力類型", max_length=20, choices=EnergyType.choices)
    active = models.BooleanField("啟用中", default=True)

    class Meta:
        ordering = ["brand", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["brand", "name"], name="unique_vehicle_model"
            )
        ]
        verbose_name = "車型"
        verbose_name_plural = "車型"

    def __str__(self):
        return f"{self.brand} {self.name}"


class VehicleColor(TimeStampedModel):
    vehicle_model = models.ForeignKey(
        VehicleModel,
        on_delete=models.PROTECT,
        related_name="colors",
        verbose_name="車型",
    )
    name = models.CharField("車色", max_length=80)
    active = models.BooleanField("啟用中", default=True)

    class Meta:
        ordering = ["vehicle_model", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["vehicle_model", "name"], name="unique_model_color"
            )
        ]
        verbose_name = "車色"
        verbose_name_plural = "車色"

    def __str__(self):
        return f"{self.vehicle_model}／{self.name}"


class VehicleInventory(TimeStampedModel):
    class Status(models.TextChoices):
        AVAILABLE = "available", "可銷售"
        RESERVED = "reserved", "已預留"
        TRANSFER_PENDING = "transfer_pending", "待調車"
        IN_TRANSFER = "in_transfer", "調車中"
        DELIVERY_PENDING = "delivery_pending", "待交車"
        DELIVERED = "delivered", "已交車"
        CONDITION_ISSUE = "condition_issue", "車況異常"
        SOLD = "sold", "已售出"
        INACTIVE = "inactive", "停用"

    vehicle_model = models.ForeignKey(
        VehicleModel, on_delete=models.PROTECT, verbose_name="車型"
    )
    color = models.ForeignKey(
        VehicleColor, on_delete=models.PROTECT, verbose_name="車色"
    )
    engine_number = models.CharField(
        "引擎號碼", max_length=80, blank=True, null=True, unique=True
    )
    frame_number = models.CharField(
        "車身號碼", max_length=80, blank=True, null=True, unique=True
    )
    ownership_store = models.ForeignKey(
        Store,
        on_delete=models.PROTECT,
        related_name="owned_vehicles",
        verbose_name="庫存歸屬門市",
    )
    location_store = models.ForeignKey(
        Store,
        on_delete=models.PROTECT,
        related_name="located_vehicles",
        verbose_name="實際存放門市",
    )
    received_on = models.DateField("進車日期", default=timezone.localdate)
    status = models.CharField(
        "庫存狀態", max_length=30, choices=Status.choices, default=Status.AVAILABLE
    )
    condition_note = models.TextField("車況說明", blank=True)
    condition_photo = models.ImageField(
        "車況照片", upload_to="inventory/condition/%Y/%m/", blank=True
    )
    condition_resolution = models.TextField("處理結果", blank=True)

    class Meta:
        ordering = ["-received_on", "-id"]
        verbose_name = "實體庫存車輛"
        verbose_name_plural = "實體庫存車輛"

    @property
    def identifier(self):
        return self.engine_number or self.frame_number or "尚未填寫"

    def clean(self):
        errors = {}
        if self.color_id and self.vehicle_model_id:
            if self.color.vehicle_model_id != self.vehicle_model_id:
                errors["color"] = "此車色不屬於選定車型。"
        if self.vehicle_model_id:
            if self.vehicle_model.energy_type == VehicleModel.EnergyType.GAS:
                if not self.engine_number:
                    errors["engine_number"] = "油車必須填寫引擎號碼。"
                if self.frame_number:
                    errors["frame_number"] = "油車第一階段不使用車身號碼。"
            else:
                if not self.frame_number:
                    errors["frame_number"] = "電動車必須填寫車身號碼。"
                if self.engine_number:
                    errors["engine_number"] = "電動車第一階段不使用引擎號碼。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.engine_number = self.engine_number.strip().upper() if self.engine_number else None
        self.frame_number = self.frame_number.strip().upper() if self.frame_number else None
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.vehicle_model} {self.color.name}／{self.identifier}"


class SalesOrder(TimeStampedModel):
    class SourceType(models.TextChoices):
        STORE = "store", "本店"
        DEALER = "dealer", "合作車行"
        PLATFORM = "platform", "網路平台"

    class OwnerType(models.TextChoices):
        LOCAL = "local", "本國自然人"
        FOREIGN = "foreign", "外籍／居留者"
        COMPANY = "company", "法人"

    class PaymentType(models.TextChoices):
        CASH = "cash", "全現金"
        INSTALLMENT = "installment", "全分期"

    class PaymentMethod(models.TextChoices):
        CASH = "cash", "現金"
        TRANSFER = "transfer", "匯款"
        CARD = "card", "刷卡"
        OTHER = "other", "其他"

    class PlateChoice(models.TextChoices):
        NONE = "none", "不選號"
        WATCH = "watch", "指定號碼監控"
        PREFERENCE = "preference", "一般領牌偏好"

    class DeliveryMethod(models.TextChoices):
        STORE_PICKUP = "store_pickup", "客人來店取車"
        DEALER_PICKUP = "dealer_pickup", "合作車行領車"
        DIRECT_DELIVERY = "direct_delivery", "送至指定地點"
        CARRIER = "carrier", "委託託運公司"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        CONTRACT_PENDING = "contract_pending", "待簽署合約"
        ALLOCATION_PENDING = "allocation_pending", "待配車"
        ALLOCATED = "allocated", "已配車"
        TRANSFER_PENDING = "transfer_pending", "待調車"
        IN_TRANSFER = "in_transfer", "調車中"
        DELIVERY_PENDING = "delivery_pending", "待交車"
        DELIVERED_DOCS_PENDING = "delivered_docs_pending", "已交車／待補文件"
        COMPLETED = "completed", "已完成"
        CANCEL_REFUND_PENDING = "cancel_refund_pending", "取消待退款"
        CANCELLED = "cancelled", "已取消／已退款"

    number = models.CharField("訂單編號", max_length=24, unique=True, editable=False)
    order_date = models.DateField("訂單日期", default=timezone.localdate)
    source_type = models.CharField(
        "訂單來源", max_length=20, choices=SourceType.choices, default=SourceType.STORE
    )
    source = models.ForeignKey(
        SalesSource,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        verbose_name="來源名稱",
    )
    status = models.CharField(
        "訂單狀態",
        max_length=32,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    owner_type = models.CharField(
        "車主類型", max_length=20, choices=OwnerType.choices, default=OwnerType.LOCAL
    )
    owner_name = models.CharField("車主姓名／公司名稱", max_length=160)
    owner_name_en = models.CharField("英文姓名", max_length=160, blank=True)
    owner_phone = models.CharField("電話", max_length=30)
    owner_email = models.EmailField("Email", blank=True)
    owner_birth_date = models.DateField("生日", blank=True, null=True)
    owner_nationality = models.CharField("國籍", max_length=80, blank=True)
    owner_address = models.TextField("戶籍／公司地址")
    owner_id_number = models.CharField("證件號碼／統一編號", max_length=40)
    residence_expiry = models.DateField("居留期限", blank=True, null=True)
    id_front = models.ImageField("證件正面", upload_to="orders/id/%Y/%m/", blank=True)
    id_back = models.ImageField("證件反面", upload_to="orders/id/%Y/%m/", blank=True)
    id_verified = models.BooleanField("已人工核對證件", default=False)
    id_verified_at = models.DateTimeField("證件核對時間", blank=True, null=True)

    vehicle_model = models.ForeignKey(
        VehicleModel, on_delete=models.PROTECT, verbose_name="車型"
    )
    color = models.ForeignKey(
        VehicleColor, on_delete=models.PROTECT, verbose_name="車色"
    )
    allocated_vehicle = models.OneToOneField(
        VehicleInventory,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="active_order",
        verbose_name="已配車輛",
    )

    payment_type = models.CharField(
        "主要付款方式",
        max_length=20,
        choices=PaymentType.choices,
        default=PaymentType.CASH,
    )
    vehicle_price = models.DecimalField(
        "車價", max_digits=12, decimal_places=0, default=0
    )
    plate_insurance_fee = models.DecimalField(
        "牌險", max_digits=12, decimal_places=0, default=0
    )
    installment_opening_fee = models.DecimalField(
        "分期開辦費", max_digits=12, decimal_places=0, default=0
    )
    other_fee = models.DecimalField(
        "其他費用", max_digits=12, decimal_places=0, default=0
    )
    discount_amount = models.DecimalField(
        "折扣／抵扣", max_digits=12, decimal_places=0, default=0
    )
    deposit_amount = models.DecimalField(
        "訂金", max_digits=12, decimal_places=0, default=0
    )
    deposit_date = models.DateField("訂金日期", blank=True, null=True)
    deposit_method = models.CharField(
        "訂金付款方式",
        max_length=20,
        choices=PaymentMethod.choices,
        blank=True,
    )
    calculated_balance = models.DecimalField(
        "系統試算尾款", max_digits=12, decimal_places=0, default=0, editable=False
    )
    actual_balance = models.DecimalField(
        "實際尾款", max_digits=12, decimal_places=0, default=0
    )
    balance_adjustment_reason = models.TextField("尾款調整原因", blank=True)

    installment_company = models.CharField("融資公司", max_length=100, blank=True)
    installment_amount = models.DecimalField(
        "分期申請金額", max_digits=12, decimal_places=0, default=0
    )
    installment_periods = models.PositiveSmallIntegerField("分期期數", default=0)
    installment_monthly = models.DecimalField(
        "每期金額", max_digits=12, decimal_places=0, default=0
    )
    installment_applied_on = models.DateField("分期申請日期", blank=True, null=True)
    installment_status = models.CharField("分期狀態", max_length=30, blank=True)
    installment_decided_on = models.DateField("核准／拒絕日期", blank=True, null=True)

    is_trade_in_subsidy = models.BooleanField("申請汰舊／政府補助", default=False)
    trade_in_plate = models.CharField("舊車車牌", max_length=20, blank=True)
    subsidy_type = models.CharField("補助類型", max_length=120, blank=True)
    old_vehicle_valuation = models.DecimalField(
        "舊車估價", max_digits=12, decimal_places=0, default=0
    )
    old_vehicle_tax = models.DecimalField(
        "舊車未繳稅金", max_digits=12, decimal_places=0, default=0
    )

    plate_choice = models.CharField(
        "選號方式",
        max_length=20,
        choices=PlateChoice.choices,
        default=PlateChoice.NONE,
    )
    watched_numbers = models.TextField("指定號碼與志願序", blank=True)
    plate_preference_note = models.TextField("領牌偏好備註", blank=True)
    final_plate_number = models.CharField("最終車牌號碼", max_length=20, blank=True)

    delivery_method = models.CharField(
        "交車方式", max_length=30, choices=DeliveryMethod.choices, blank=True
    )
    note = models.TextField("備註", blank=True)
    signed_contract = models.FileField(
        "已簽署合約", upload_to="orders/contracts/%Y/%m/", blank=True
    )
    signed_contract_uploaded_at = models.DateTimeField(
        "合約上傳時間", blank=True, null=True
    )

    class Meta:
        ordering = ["-order_date", "-id"]
        verbose_name = "銷售訂單"
        verbose_name_plural = "銷售訂單"
        indexes = [
            models.Index(fields=["number"]),
            models.Index(fields=["owner_name"]),
            models.Index(fields=["owner_phone"]),
            models.Index(fields=["owner_id_number"]),
            models.Index(fields=["status"]),
        ]

    @property
    def masked_id_number(self):
        value = self.owner_id_number or ""
        if len(value) <= 4:
            return "＊" * len(value)
        return f"{value[:2]}{'＊' * (len(value) - 4)}{value[-2:]}"

    @property
    def has_signed_contract(self):
        return bool(self.signed_contract)

    def calculate_balance(self):
        accessories = sum(line.line_total for line in self.accessories.all()) if self.pk else 0
        return (
            self.vehicle_price
            + self.plate_insurance_fee
            + self.installment_opening_fee
            + self.other_fee
            + self.old_vehicle_tax
            + accessories
            - self.discount_amount
            - self.deposit_amount
            - self.old_vehicle_valuation
        )

    def clean(self):
        errors = {}
        if self.source_type == self.SourceType.STORE and self.source_id:
            errors["source"] = "本店訂單不需選擇來源名稱。"
        if self.source_type != self.SourceType.STORE and not self.source_id:
            errors["source"] = "合作車行或網路平台訂單必須選擇來源名稱。"
        if self.source_id and self.source.source_type != self.source_type:
            errors["source"] = "來源名稱與訂單來源類型不一致。"
        if self.color_id and self.vehicle_model_id:
            if self.color.vehicle_model_id != self.vehicle_model_id:
                errors["color"] = "此車色不屬於選定車型。"
        if (
            self.pk
            and self.actual_balance != self.calculated_balance
            and not self.balance_adjustment_reason
        ):
            errors["balance_adjustment_reason"] = "修改系統試算尾款時必須填寫原因。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = f"SO{timezone.localdate():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"
        if self.id_verified and not self.id_verified_at:
            self.id_verified_at = timezone.now()
        if self.signed_contract and not self.signed_contract_uploaded_at:
            self.signed_contract_uploaded_at = timezone.now()
        if self.pk:
            self.calculated_balance = self.calculate_balance()
        if self.status == self.Status.DRAFT:
            self.status = (
                self.Status.ALLOCATION_PENDING
                if self.signed_contract
                else self.Status.CONTRACT_PENDING
            )
        self.full_clean()
        return super().save(*args, **kwargs)

    @transaction.atomic
    def allocate(self, vehicle):
        locked = VehicleInventory.objects.select_for_update().get(pk=vehicle.pk)
        if not self.signed_contract:
            raise ValidationError("尚未上傳已簽署合約，不得配車。")
        if self.allocated_vehicle_id:
            raise ValidationError("此訂單已配車，請先解除原配車。")
        if locked.status != VehicleInventory.Status.AVAILABLE:
            raise ValidationError("此車輛目前不可配車。")
        if (
            locked.vehicle_model_id != self.vehicle_model_id
            or locked.color_id != self.color_id
        ):
            raise ValidationError("實體車輛的車型或車色與訂單不一致。")
        locked.status = VehicleInventory.Status.RESERVED
        locked.save(update_fields=["status", "updated_at"])
        self.allocated_vehicle = locked
        self.status = self.Status.ALLOCATED
        self.save(update_fields=["allocated_vehicle", "status", "updated_at"])

    def __str__(self):
        return f"{self.number}／{self.owner_name}"


class AccessoryLine(TimeStampedModel):
    class LineType(models.TextChoices):
        PURCHASE = "purchase", "加購"
        GIFT = "gift", "贈送"

    order = models.ForeignKey(
        SalesOrder, on_delete=models.CASCADE, related_name="accessories"
    )
    name = models.CharField("配件名稱", max_length=160)
    quantity = models.PositiveSmallIntegerField("數量", default=1)
    line_type = models.CharField(
        "類型", max_length=20, choices=LineType.choices, default=LineType.PURCHASE
    )
    amount = models.DecimalField("金額", max_digits=12, decimal_places=0, default=0)
    installed_on = models.DateField("安裝日期", blank=True, null=True)
    note = models.CharField("備註", max_length=250, blank=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "配件"
        verbose_name_plural = "配件"

    @property
    def line_total(self):
        if self.line_type == self.LineType.GIFT:
            return 0
        return self.amount * self.quantity

    def __str__(self):
        return self.name


class OrderEvent(TimeStampedModel):
    order = models.ForeignKey(
        SalesOrder, on_delete=models.CASCADE, related_name="events"
    )
    event_type = models.CharField("事件類型", max_length=50)
    description = models.TextField("內容")
    actor_name = models.CharField("操作人員", max_length=150, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "訂單事件"
        verbose_name_plural = "訂單事件"
