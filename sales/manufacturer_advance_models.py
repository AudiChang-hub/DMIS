"""原廠代墊／代轉追蹤（T-334 第一版，A 案）。

原廠活動的獎金或贈品：我們先給客人或車行、原廠之後補給我們（代墊），或原廠先撥給我們、我們再轉交（代轉）。
這筆錢只是左手進、右手出：不算淨利、不動客戶應收、不擋交車，也不進收支帳本與統一撥款對帳。
兩個勾選各自獨立：「原廠已撥」「已交給對象」都勾了才算結清。

第二版（T-337）加「依活動自動掛上」：ManufacturerAdvanceCampaign 設定活動，符合條件的訂單依實際領牌日自動掛上
（origin=campaign、origin_key=campaign:<活動 id>，同一張單同一個活動只有一筆）；單張訂單可標「不適用」
（ManufacturerAdvanceExclusion），之後不再自動掛回去。
"""
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.signals import post_save


class ManufacturerAdvancePayout(models.Model):
    """原廠撥款紀錄：一次撥款涵蓋哪些項目（反向 `items`）。差額＝實撥－項目金額合計，只顯示，不存、不進收支。"""

    manufacturer = models.CharField("原廠", max_length=80)
    paid_on = models.DateField("撥款日")
    amount = models.DecimalField("實撥金額", max_digits=12, decimal_places=0)
    handled_by = models.CharField("經手人", max_length=150)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="登記帳號",
    )
    voided_at = models.DateTimeField("復原時間", null=True, blank=True)
    voided_by = models.CharField("復原人員", max_length=150, blank=True)
    created_at = models.DateTimeField("建立時間", auto_now_add=True)
    updated_at = models.DateTimeField("更新時間", auto_now=True)

    class Meta:
        ordering = ["-paid_on", "-id"]
        verbose_name = "原廠撥款紀錄"
        verbose_name_plural = "原廠撥款紀錄"
        constraints = [
            models.CheckConstraint(condition=Q(amount__gte=0), name="manufacturer_payout_amount_non_negative"),
        ]

    def __str__(self):
        return f"{self.manufacturer} {self.paid_on:%Y/%m/%d} ${self.amount:,.0f}"


class ManufacturerAdvance(models.Model):
    """一張訂單的一筆代墊／代轉項目。作廢（voided_at）代替刪除，可以復原。"""

    class Recipient(models.TextChoices):
        CUSTOMER = "customer", "客人"
        DEALER = "dealer", "車行"

    class Kind(models.TextChoices):
        CASH = "cash", "金額"
        GIFT = "gift", "贈品"

    class Origin(models.TextChoices):
        MANUAL = "manual", "手動"
        CAMPAIGN = "campaign", "依活動自動掛上"

    order = models.ForeignKey(
        "sales.SalesOrder", on_delete=models.CASCADE, related_name="manufacturer_advances", verbose_name="訂單",
    )
    manufacturer = models.CharField("原廠", max_length=80)
    campaign_name = models.CharField("活動名稱", max_length=120)
    recipient = models.CharField("對象", max_length=12, choices=Recipient.choices, default=Recipient.CUSTOMER)
    kind = models.CharField("內容", max_length=12, choices=Kind.choices, default=Kind.CASH)
    amount = models.DecimalField("金額", max_digits=12, decimal_places=0, default=0)
    gift_name = models.CharField("贈品名稱", max_length=120, blank=True)
    gift_quantity = models.PositiveIntegerField("贈品數量", default=0)

    reimbursed_on = models.DateField("原廠撥款日", null=True, blank=True)
    reimbursed_by = models.CharField("原廠已撥經手人", max_length=150, blank=True)
    reimbursed_at = models.DateTimeField("勾原廠已撥的時間", null=True, blank=True)
    payout = models.ForeignKey(
        ManufacturerAdvancePayout, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="items", verbose_name="對應的撥款紀錄",
    )

    handed_over_on = models.DateField("交給對象日", null=True, blank=True)
    handed_over_by = models.CharField("交給對象經手人", max_length=150, blank=True)
    handed_over_at = models.DateTimeField("勾已交給對象的時間", null=True, blank=True)

    origin = models.CharField("建立方式", max_length=20, choices=Origin.choices, default=Origin.MANUAL)
    origin_key = models.CharField("自動掛單代碼", max_length=160, blank=True)
    # T-337：依活動自動掛上的項目記是哪個活動；手動新增的是空的。有掛單的活動不能刪除（改停用）。
    campaign = models.ForeignKey(
        "sales.ManufacturerAdvanceCampaign", on_delete=models.PROTECT, null=True, blank=True,
        related_name="advance_items", verbose_name="來源活動",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="建立帳號",
    )
    created_by_name = models.CharField("建立人員", max_length=150, blank=True)
    voided_at = models.DateTimeField("刪除時間", null=True, blank=True)
    voided_by = models.CharField("刪除人員", max_length=150, blank=True)
    created_at = models.DateTimeField("建立時間", auto_now_add=True)
    updated_at = models.DateTimeField("更新時間", auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name = "原廠代墊／代轉"
        verbose_name_plural = "原廠代墊／代轉"
        constraints = [
            models.CheckConstraint(condition=Q(amount__gte=0), name="manufacturer_advance_amount_non_negative"),
            models.UniqueConstraint(
                fields=["order", "origin_key"], condition=~Q(origin_key=""),
                name="manufacturer_advance_unique_origin_key",
            ),
        ]
        indexes = [
            models.Index(fields=["voided_at", "reimbursed_at"], name="mfr_advance_reimburse_idx"),
            models.Index(fields=["voided_at", "handed_over_at"], name="mfr_advance_handover_idx"),
        ]

    def __str__(self):
        return f"{self.campaign_name}（{self.content_label}）"

    @property
    def is_cash(self):
        return self.kind == self.Kind.CASH

    @property
    def content_label(self):
        if self.is_cash:
            return f"${self.amount:,.0f}"
        return f"{self.gift_name} × {self.gift_quantity}"

    @property
    def reimbursed(self):
        return self.reimbursed_at is not None

    @property
    def handed_over(self):
        return self.handed_over_at is not None

    @property
    def settled(self):
        return self.reimbursed and self.handed_over

    @staticmethod
    def _stamp(on, by):
        if not on:
            return ""
        return f"{on:%m/%d}　{by}" if by else f"{on:%m/%d}"

    @property
    def reimbursed_label(self):
        return self._stamp(self.reimbursed_on, self.reimbursed_by)

    @property
    def handed_over_label(self):
        return self._stamp(self.handed_over_on, self.handed_over_by)


class ManufacturerAdvanceCampaign(models.Model):
    """代墊／代轉活動（T-337）：比照原廠獎勵活動，欄位精簡。

    符合條件（原廠＝訂單車型品牌、適用車型留白＝該原廠全部車型、期間涵蓋日期、對象是車行時只限車行單）的訂單：
    已確認實際領牌的，依實際領牌日自動掛上一筆代墊／代轉；還沒領牌的，依訂單日期在訂單頁顯示「預計適用」（不建項目）。
    """

    name = models.CharField("活動名稱", max_length=120)
    manufacturer = models.CharField("原廠", max_length=80)
    effective_from = models.DateField("開始日")
    effective_to = models.DateField("結束日", null=True, blank=True)
    vehicle_models = models.ManyToManyField(
        "sales.VehicleModel", blank=True, related_name="manufacturer_advance_campaigns", verbose_name="適用車型",
    )
    recipient = models.CharField("對象", max_length=12, choices=ManufacturerAdvance.Recipient.choices,
                                 default=ManufacturerAdvance.Recipient.CUSTOMER)
    kind = models.CharField("內容", max_length=12, choices=ManufacturerAdvance.Kind.choices,
                            default=ManufacturerAdvance.Kind.CASH)
    amount = models.DecimalField("金額", max_digits=12, decimal_places=0, default=0)
    gift_name = models.CharField("贈品名稱", max_length=120, blank=True)
    gift_quantity = models.PositiveIntegerField("贈品數量", default=0)
    active = models.BooleanField("啟用", default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="建立帳號",
    )
    created_at = models.DateTimeField("建立時間", auto_now_add=True)
    updated_at = models.DateTimeField("更新時間", auto_now=True)

    class Meta:
        ordering = ["-effective_from", "-id"]
        verbose_name = "代墊／代轉活動"
        verbose_name_plural = "代墊／代轉活動"
        constraints = [
            models.CheckConstraint(condition=Q(amount__gte=0), name="manufacturer_advance_campaign_amount_non_negative"),
        ]

    def __str__(self):
        return self.name

    @property
    def is_cash(self):
        return self.kind == ManufacturerAdvance.Kind.CASH

    @property
    def content_label(self):
        if self.is_cash:
            return f"${self.amount:,.0f}"
        return f"{self.gift_name} × {self.gift_quantity}"

    @property
    def origin_key(self):
        return f"campaign:{self.pk}"


class ManufacturerAdvanceExclusion(models.Model):
    """單張訂單標「不適用」某個代墊／代轉活動（T-337）：從該單移除，之後也不再自動掛回去；可以復原。"""

    order = models.ForeignKey(
        "sales.SalesOrder", on_delete=models.CASCADE, related_name="manufacturer_advance_exclusions", verbose_name="訂單",
    )
    campaign = models.ForeignKey(
        ManufacturerAdvanceCampaign, on_delete=models.CASCADE, related_name="exclusions", verbose_name="活動",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="標記帳號",
    )
    created_by_name = models.CharField("標記人員", max_length=150, blank=True)
    created_at = models.DateTimeField("標記時間", auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name = "代墊／代轉不適用"
        verbose_name_plural = "代墊／代轉不適用"
        constraints = [
            models.UniqueConstraint(fields=["order", "campaign"], name="manufacturer_advance_exclusion_unique"),
        ]

    def __str__(self):
        return f"{self.order_id} 不適用 {self.campaign}"


def _order_saved(sender, **kwargs):
    """T-337 自動掛單：訂單存檔（交易提交後）依活動條件重新比對；邏輯在 services/manufacturer_advance_campaign.py。"""
    from sales.services.manufacturer_advance_campaign import order_saved

    order_saved(sender, **kwargs)


post_save.connect(_order_saved, sender="sales.SalesOrder", dispatch_uid="t337_manufacturer_advance_auto_attach")
