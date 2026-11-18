"""匯出紀錄基準值的保存期限（T-232 Q7：30 天）。

基準值是回匯三方比對用的「匯出當時的值」，可能含個資；到期後清空、只留摘要（人、時間、範圍、欄位、張數），
那份 Excel 就不能再回匯，要重新匯出。每次確認匯出時順手清一次，另有 `expire_order_export_baselines` 指令可排程。
"""
from datetime import timedelta

from django.utils import timezone

from sales.models import OrderExportRecord

from .columns import BASELINE_DAYS


def baseline_cutoff(now=None):
    return (now or timezone.now()) - timedelta(days=BASELINE_DAYS)


def is_expired(record, now=None):
    return record.baseline_cleared_at is not None or record.created_at < baseline_cutoff(now)


def expire_baselines(now=None):
    """清掉超過保存天數的基準值；回傳清掉幾筆。"""
    now = now or timezone.now()
    return OrderExportRecord.objects.filter(
        created_at__lt=baseline_cutoff(now), baseline_cleared_at__isnull=True,
    ).update(baseline={}, baseline_cleared_at=now)
