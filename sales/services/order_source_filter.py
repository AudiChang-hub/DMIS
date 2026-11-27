"""全部訂單「車行／平台」篩選（T-323，使用者 2026-11-27）。

只比對訂單來源，也就是列表「車行／平台」欄顯示的那一家（SalesOrder.source_display）；
不看歸屬車行（commission_recipient）、備註或其他文字。Excel 匯入單在列表顯示的是對應後的來源主檔，
所以同樣用來源主檔比對；沒對應到來源的匯入單顯示成「馭盛」，選「馭盛」就篩得到。

網址參數 src：逗號分隔，可混用
  - 來源主檔編號（例如 12）
  - house：顯示成「馭盛」的本店單（沒有來源，或來源名稱是「本店」「馭盛」）
  - store／dealer／platform：整組（訂單來源類型）
選項與摘要文字的規則和 static/js/order-source-filter.js 一致，改一邊要改另一邊。
"""
from django.db.models import Q

from sales.models import SalesOrder, SalesSource

PARAM = "src"
LABEL = "車行／平台"
HOUSE = "house"
HOUSE_LABEL = "馭盛"
# SalesOrder.source_display 把沒有來源、或來源名稱是「本店」的本店單顯示成「馭盛」；名稱就叫「馭盛」的本店來源顯示也一樣，併成同一項。
HOUSE_SOURCE_NAMES = ("", "本店", HOUSE_LABEL)
GROUPS = tuple((value, label) for value, label in SalesOrder.SourceType.choices)
GROUP_KEYS = tuple(key for key, _label in GROUPS)
MAX_TOKENS = 300


def parse_tokens(raw):
    tokens = []
    for part in str(raw or "").split(","):
        part = part.strip()
        valid = part == HOUSE or part in GROUP_KEYS or (part.isascii() and part.isdigit() and len(part) <= 9)
        if valid and part not in tokens:
            tokens.append(part)
    return tokens[:MAX_TOKENS]


def source_q(tokens):
    query = Q()
    kinds = [token for token in tokens if token in GROUP_KEYS]
    ids = [int(token) for token in tokens if token.isdigit()]
    if kinds:
        query |= Q(source_type__in=kinds)
    if ids:
        query |= Q(source_id__in=ids)
    if HOUSE in tokens:
        query |= Q(source_type=SalesOrder.SourceType.STORE) & (
            Q(source__isnull=True) | Q(source__name__in=HOUSE_SOURCE_NAMES))
    return query


def has_source_filter(params):
    """有沒有有效的車行／平台條件；無效值（打錯的網址）當作沒選，頁籤與筆數和沒帶時一樣。"""
    return bool(parse_tokens(params.get(PARAM)))


def filter_by_source(rows, raw):
    """沒選（或參數全是無效值）時原樣回傳，不加任何條件。"""
    tokens = parse_tokens(raw)
    return rows.filter(source_q(tokens)) if tokens else rows


def source_groups():
    """選擇器的選項：本店、車行、網路平台三組；停用的照樣列出並標記。"""
    members = {key: [] for key in GROUP_KEYS}
    names = {}
    rows = SalesSource.objects.order_by("-active", "name", "pk").values_list("pk", "name", "source_type", "active")
    for pk, name, kind, active in rows:
        names[str(pk)] = name
        if kind not in members or (kind == SalesSource.SourceType.STORE and name in HOUSE_SOURCE_NAMES):
            continue
        option = {"value": str(pk), "label": name}
        if not active:
            option["inactive"] = True
        members[kind].append(option)
    members[SalesSource.SourceType.STORE].insert(0, {"value": HOUSE, "label": HOUSE_LABEL})
    groups = [{"key": key, "label": label, "all": f"全部{label}", "options": members[key]} for key, label in GROUPS]
    return groups, names


def selected_labels(tokens, groups, names=None):
    """依選項順序列出選到的名稱；整組選了就只列「全部車行」這類一項，不再逐家列。"""
    chosen, labels, known = set(tokens), [], set()
    for group in groups:
        known.add(group["key"])
        known.update(option["value"] for option in group["options"])
        if group["key"] in chosen:
            labels.append((group["key"], group["all"]))
            continue
        labels.extend((option["value"], option["label"]) for option in group["options"] if option["value"] in chosen)
    # 不在選項裡的編號（併進「馭盛」的本店來源、已不存在的來源）照樣列出，畫面才對得上實際條件。
    labels.extend((token, (names or {}).get(token) or "不存在的來源") for token in tokens if token not in known)
    return labels


def summarize(labels, group_keys=GROUP_KEYS):
    """「示範車行甲、示範車行乙」；超過兩項寫「示範車行甲 等 3 家」（含整組時單位改「項」）。"""
    if len(labels) <= 2:
        return "、".join(label for _value, label in labels)
    unit = "項" if any(value in group_keys for value, _label in labels) else "家"
    return f"{labels[0][1]} 等 {len(labels)} {unit}"


def source_filter_context(raw):
    groups, names = source_groups()
    labels = selected_labels(parse_tokens(raw), groups, names)
    return {
        "param": PARAM, "label": LABEL, "groups": groups,
        "value": ",".join(value for value, _label in labels),
        "summary": summarize(labels),
        "names": "、".join(label for _value, label in labels),
    }
