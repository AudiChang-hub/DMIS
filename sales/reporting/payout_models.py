"""車行傭金／獎金給付追蹤（T-150 方案 A，使用者 2026-11-11 選定）。

應付金額每次打開頁面即時計算（`sales/reporting/payouts.py`），這裡只記：
勾了沒、給付當下的金額／數量快照、備註，以及每次操作的歷程。
不影響車行結算、掛帳、淨利與收支帳本。
"""
from django.db import models


class DealerPayoutEntry(models.Model):
    class Kind(models.TextChoices):
        COMMISSION = "commission", "傭金"
        REWARD = "reward", "實物獎勵"
        VOLUME_BONUS = "volume_bonus", "台數獎金"

    # 例：commission:order:123、reward:order:123:campaign:5:item:7、volume_bonus:rule:3:period:9:dealer:4
    source_key = models.CharField("來源代碼", max_length=160, unique=True)
    kind = models.CharField("項目類型", max_length=20, choices=Kind.choices)
    dealer = models.ForeignKey(
        "sales.SalesSource", on_delete=models.PROTECT, related_name="payout_entries", verbose_name="車行",
    )
    order = models.ForeignKey(
        "sales.SalesOrder", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="payout_entries", verbose_name="訂單",
    )
    label = models.CharField("項目名稱", max_length=200)
    paid = models.BooleanField("已給付", default=False)
    paid_amount = models.DecimalField("給付時金額", max_digits=12, decimal_places=0, null=True, blank=True)
    paid_quantity = models.DecimalField("給付時數量", max_digits=12, decimal_places=2, null=True, blank=True)
    paid_unit = models.CharField("單位", max_length=20, blank=True)
    paid_at = models.DateTimeField("給付時間", null=True, blank=True)
    paid_by = models.CharField("給付登記人", max_length=150, blank=True)
    note = models.TextField("備註", blank=True)
    resolved_at = models.DateTimeField("來源消失已處理", null=True, blank=True)
    resolved_by = models.CharField("處理人", max_length=150, blank=True)
    created_at = models.DateTimeField("建立時間", auto_now_add=True)
    updated_at = models.DateTimeField("更新時間", auto_now=True)

    class Meta:
        app_label = "sales"
        ordering = ["dealer_id", "order_id", "pk"]
        indexes = [models.Index(fields=["dealer", "paid"], name="payout_dealer_paid_idx")]
        verbose_name = "車行給付紀錄"
        verbose_name_plural = "車行給付紀錄"

    def __str__(self):
        return f"{self.label}（{'已給付' if self.paid else '未給付'}）"


class DealerPayoutEvent(models.Model):
    class Action(models.TextChoices):
        PAID = "paid", "標記已給付"
        UNPAID = "unpaid", "取消已給付"
        NOTE = "note", "修改備註"
        CONFIRM_DIFFERENCE = "confirm_difference", "確認差額"
        RESOLVE = "resolve", "來源消失確認處理"

    entry = models.ForeignKey(DealerPayoutEntry, on_delete=models.CASCADE, related_name="events", verbose_name="給付紀錄")
    action = models.CharField("動作", max_length=24, choices=Action.choices)
    amount = models.DecimalField("當時金額", max_digits=12, decimal_places=0, null=True, blank=True)
    quantity = models.DecimalField("當時數量", max_digits=12, decimal_places=2, null=True, blank=True)
    note_before = models.TextField("原備註", blank=True)
    note_after = models.TextField("新備註", blank=True)
    actor_name = models.CharField("操作人", max_length=150, blank=True)
    created_at = models.DateTimeField("時間", auto_now_add=True)

    class Meta:
        app_label = "sales"
        ordering = ["-created_at", "-pk"]
        verbose_name = "車行給付歷程"
        verbose_name_plural = "車行給付歷程"
