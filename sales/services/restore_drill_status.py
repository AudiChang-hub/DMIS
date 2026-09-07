"""僅提供管理者頁面使用的還原演練摘要，不傳回原始紀錄。"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from django.conf import settings


def restore_drill_status():
    fallback = {"label": "尚無有效演練紀錄", "success": False}
    path = settings.RESTORE_DRILL_STATUS_PATH
    if not path:
        return fallback
    try:
        with Path(path).open(encoding="utf-8") as stream:
            raw = json.loads(stream.read(8192))
        when = datetime.fromisoformat(raw["checked_at"])
        age = datetime.now(timezone.utc) - when
        status = raw["status"]
        labels = {"success": "隔離還原演練通過", "failed": "還原演練失敗，請管理者檢查", "running": "還原演練進行中"}
        if status not in labels or age < timedelta(0):
            return fallback
        stale = age > (timedelta(hours=1) if status == "running" else timedelta(days=8))
        result = {"label": "演練紀錄逾期，請檢查排程" if stale else labels[status],
                  "success": status == "success" and not stale, "checked_at": when}
        if status == "success":
            for key in ("tables", "rows", "media_files", "duration_seconds"):
                value = raw[key]
                if type(value) is not int or value < 0:
                    return fallback
                result[key] = value
        return result
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return fallback
