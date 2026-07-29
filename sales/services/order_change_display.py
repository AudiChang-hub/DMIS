from collections import Counter
from decimal import Decimal, InvalidOperation

from sales.models import SalesOrder


GROUPS = (
    (
        "車主資料",
        {
            "車主類型",
            "車主姓名／公司名稱",
            "英文姓名",
            "電話",
            "Email",
            "生日",
            "國籍",
            "戶籍／公司地址",
            "證件號碼／統一編號",
            "居留期限",
            "證件正面",
            "證件反面",
            "已人工核對證件",
            "證件核對時間",
        },
    ),
    (
        "車輛與來源",
        {
            "訂單日期",
            "訂單來源",
            "來源名稱",
            "訂單狀態",
            "車型",
            "車色",
            "已配車輛",
            "車輛類別",
        },
    ),
    (
        "付款資料",
        {
            "主要付款方式",
            "車價",
            "牌險",
            "分期開辦費",
            "訂金",
            "訂金日期",
            "訂金付款方式",
            "系統試算尾款",
            "實際尾款",
            "尾款調整原因",
            "分期公司",
            "分期申請金額",
            "分期期數",
            "每期金額",
            "分期申請日期",
            "分期狀態",
            "核准／拒絕日期",
            "其他費用",
        },
    ),
    (
        "選號與補助",
        {
            "申請汰舊／政府補助",
            "舊車車牌",
            "舊車主姓名",
            "補助類型",
            "舊車估價",
            "舊車未繳稅金",
            "選號方式",
            "指定號碼與志願序",
            "領牌偏好備註",
            "最終車牌號碼",
        },
    ),
    (
        "配件與交車",
        {
            "配件",
            "交車方式",
            "送達地點／託運目的地",
            "備註",
            "已簽署合約",
            "合約上傳時間",
        },
    ),
)

MONEY_FIELDS = {
    "車價",
    "牌險",
    "分期開辦費",
    "訂金",
    "系統試算尾款",
    "實際尾款",
    "分期申請金額",
    "每期金額",
    "舊車估價",
    "舊車未繳稅金",
}
BOOLEAN_FIELDS = {"已人工核對證件", "申請汰舊／政府補助"}


def _choice_maps():
    result = {}
    for field in SalesOrder._meta.concrete_fields:
        if field.choices:
            result[str(field.verbose_name)] = {
                str(value): str(label) for value, label in field.flatchoices
            }
    return result


CHOICE_MAPS = _choice_maps()


def _money(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    return f"${amount:,.0f}"


def _format_value(label, value):
    if value in (None, ""):
        return "未填寫"
    text = str(value)
    if label in CHOICE_MAPS:
        return CHOICE_MAPS[label].get(text, text)
    if label in BOOLEAN_FIELDS:
        return "是" if text.lower() in {"true", "1", "yes"} else "否"
    if label in MONEY_FIELDS:
        return _money(value)
    return text


def _format_accessory(row):
    result = f"{row.get('名稱') or '未命名配件'} × {row.get('數量') or 1}"
    details = []
    if row.get("類型"):
        details.append(str(row["類型"]))
    if row.get("金額") not in (None, ""):
        details.append(_money(row["金額"]))
    if row.get("安裝日期"):
        details.append(f"安裝日 {row['安裝日期']}")
    if row.get("備註"):
        details.append(str(row["備註"]))
    return f"{result}（{'，'.join(details)}）" if details else result


def _format_fee(row):
    name = row.get("項目") or "未命名費用"
    return f"{name} {_money(row.get('金額', 0))}"


def _list_diff(label, values):
    formatter = _format_accessory if label == "配件" else _format_fee
    before = Counter(formatter(row) for row in values.get("before") or [])
    after = Counter(formatter(row) for row in values.get("after") or [])
    items = []
    for text, count in (after - before).items():
        items.extend({"action": "新增", "after": text} for _ in range(count))
    for text, count in (before - after).items():
        items.extend({"action": "移除", "before": text} for _ in range(count))
    return items


def build_order_change_cards(changes):
    cards = []
    for change in changes:
        grouped = {name: [] for name, _ in GROUPS}
        grouped["其他"] = []
        for label, values in change.changes.items():
            if label in {"配件", "其他費用"}:
                entries = _list_diff(label, values)
            else:
                entries = [
                    {
                        "action": "修改",
                        "label": label,
                        "before": _format_value(label, values.get("before")),
                        "after": _format_value(label, values.get("after")),
                    }
                ]
            group_name = next(
                (name for name, fields in GROUPS if label in fields), "其他"
            )
            grouped[group_name].extend(entries)
        groups = [
            {"name": name, "items": grouped[name]}
            for name, _ in GROUPS
            if grouped[name]
        ]
        if grouped["其他"]:
            groups.append({"name": "其他", "items": grouped["其他"]})
        cards.append(
            {
                "actor": change.actor_name,
                "created_at": change.created_at,
                "reason": change.reason,
                "count": sum(len(group["items"]) for group in groups),
                "groups": groups,
            }
        )
    return cards
