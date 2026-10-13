"""admin 可隨時調整的系統規則（使用者 2026-10-13）。

目前只有「優先配車月數」：出廠超過幾個月的車自動列為優先配車。讀取有快取，修改後立即生效並留下異動紀錄。
"""
import time

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction

from sales.models import ALLOCATION_PRIORITY_AGE_MONTHS, SystemSetting, SystemSettingChange

ALLOCATION_PRIORITY_AGE_KEY = "allocation_priority_age_months"
ALLOCATION_PRIORITY_AGE_RANGE = (1, 24)
_CACHE_KEY = "system-setting:" + ALLOCATION_PRIORITY_AGE_KEY
# 列表每台車都會判斷優先配車；同一程序內 5 秒內重複讀取直接用記憶值，修改後其他程序最慢 5 秒生效。
_memo = {"value": None, "until": 0.0}


def allocation_priority_age_months():
    now = time.monotonic()
    if _memo["value"] is not None and now < _memo["until"]:
        return _memo["value"]
    months = _read_months()
    _memo.update(value=months, until=now + 5)
    return months


def _read_months():
    try:
        cached = cache.get(_CACHE_KEY)
    except Exception:  # 快取服務暫時不可用時直接讀資料庫
        cached = None
    if cached is not None:
        return cached
    stored = SystemSetting.objects.filter(key=ALLOCATION_PRIORITY_AGE_KEY).values_list("value", flat=True).first()
    months = int(stored) if stored and stored.isdigit() else ALLOCATION_PRIORITY_AGE_MONTHS
    try:
        cache.set(_CACHE_KEY, months, 300)
    except Exception:
        pass
    return months


@transaction.atomic
def set_allocation_priority_age_months(months, actor):
    low, high = ALLOCATION_PRIORITY_AGE_RANGE
    if not isinstance(months, int) or not low <= months <= high:
        raise ValidationError(f"請選擇 {low}～{high} 個月。")
    setting = SystemSetting.objects.select_for_update().filter(key=ALLOCATION_PRIORITY_AGE_KEY).first()
    before = setting.value if setting else str(ALLOCATION_PRIORITY_AGE_MONTHS)
    if before == str(months):
        return False
    if setting:
        setting.value, setting.updated_by = str(months), actor
        setting.save(update_fields=["value", "updated_by", "updated_at"])
    else:
        SystemSetting.objects.create(key=ALLOCATION_PRIORITY_AGE_KEY, value=str(months), updated_by=actor)
    SystemSettingChange.objects.create(key=ALLOCATION_PRIORITY_AGE_KEY, before=before, after=str(months), actor=actor)
    _forget()
    transaction.on_commit(_forget)
    return True


def _forget():
    _memo.update(value=None, until=0.0)
    try:
        cache.delete(_CACHE_KEY)
    except Exception:
        pass
