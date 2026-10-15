"""各政府單位的補助申請進度彙整：只讀補助申請項目，不另外保存狀態。

「有送出申請」指項目狀態為已申請（2026-10-15 起只分未申請／已申請）。
"""
from sales.models import SubsidyItem

AGENCY_CATEGORIES = (
    SubsidyItem.Category.INDUSTRY,
    SubsidyItem.Category.ENVIRONMENT,
    SubsidyItem.Category.LOCAL,
)
SENT = {SubsidyItem.Status.SUBMITTED}


def _progress(count, sent):
    if not count:
        return ""
    if sent == count:
        return "已申請"
    if sent:
        return f"已申請 {sent}／{count} 筆"
    return "尚未申請"


def agency_summary(items):
    """回傳工業局、環境部、地方政府（有項目時再加「其他」）各一列。

    items 可傳入已預先載入的項目，避免逐訂單查詢。
    """
    items = list(items)
    labels = dict(SubsidyItem.Category.choices)
    rows = []
    for category in (*AGENCY_CATEGORIES, SubsidyItem.Category.OTHER):
        group = [item for item in items if item.category == category]
        if category == SubsidyItem.Category.OTHER and not group:
            continue
        count = len(group)
        sent = sum(1 for item in group if item.status in SENT)
        total = sum((item.expected_amount for item in group), 0)
        progress = _progress(count, sent)
        rows.append({
            "category": category,
            "label": labels[category],
            "count": count,
            "total": total,
            "sent": sent,
            "progress": progress,
            "text": f"{progress}（{count} 筆，合計 ${total:,.0f}）" if count else "",
        })
    return rows
