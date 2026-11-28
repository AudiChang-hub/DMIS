"""原廠代墊／代轉追蹤（T-334 第一版，A 案）。

原廠活動的獎金或贈品：我們先給客人或車行、原廠之後補給我們（代墊），或原廠先撥給我們、我們再轉交（代轉）。
這筆錢只是左手進、右手出：不算淨利、不動客戶應收、不擋交車，也不進收支帳本與統一撥款對帳。
兩個勾選各自獨立：「原廠已撥」「已交給對象」都勾了才算結清。

第二版會加「依活動自動掛上」：`origin`／`origin_key` 先預留，自動掛單用 origin_key 冪等（同一張單同一個 key 只有一筆）。
"""
from django.conf import settings
from django.db import models
from django.db.models import Q


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
