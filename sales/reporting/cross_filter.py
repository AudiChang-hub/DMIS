"""有界的跨圖選取；只引用發布圖表與現有下鑽白名單，不接受查詢欄位。"""
import json

from django.core.exceptions import ValidationError


def selections(raw):
    if not raw:
        return []
    try:
        if not isinstance(raw, str) or len(raw) > 6000:
            raise ValueError
        values = json.loads(raw)
        if not isinstance(values, list) or len(values) > 8:
            raise ValueError
        seen = set()
        for item in values:
            if not isinstance(item, dict) or set(item) != {"card", "group", "grain"}:
                raise ValueError
            if type(item["card"]) is not int or not 0 <= item["card"] < 8 or item["card"] in seen:
                raise ValueError
            seen.add(item["card"])
            groups = item["group"] if isinstance(item["group"], list) else [item["group"]]
            if not 1 <= len(groups) <= 200 or any(not isinstance(group, str) or not 0 < len(group) <= 600 or group == "__all__" for group in groups):
                raise ValueError
            if len(set(groups)) != len(groups):
                raise ValueError
            if item["grain"] not in ("", "year", "month", "day"):
                raise ValueError
            if any(group.startswith("o:") for group in groups):
                raise ValidationError("合併的其他系列目前請用明細模式查看，不能作為全頁交叉篩選。")
        return values
    except (ValueError, TypeError, RecursionError):
        raise ValidationError("圖表選取條件不正確，請清除圖表選取後再試。")


def selection_label(config, item):
    if isinstance(item["group"], list):
        return "、".join(selection_label(config, {**item, "group": group}) for group in item["group"])
    from .engine import decode_key, dimension_label, dimension_labels, effective_card
    try:
        card = effective_card(config["cards"][item["card"]], {"grain": item["grain"]})
        key = item["group"]
        keys = json.loads(key[2:]) if key.startswith("c:") else [key]
        dimensions = [card["dimension"], card.get("series")]
        labels = []
        for dimension, encoded in zip(dimensions, keys):
            raw = decode_key(dimension, encoded)
            labels.append(dimension_label(dimension, raw, dimension_labels(dimension, [] if raw is None else [raw])))
        return " · ".join(labels)
    except (ValueError, TypeError, KeyError, RecursionError, ValidationError):
        return "無效分類（請移除）"
