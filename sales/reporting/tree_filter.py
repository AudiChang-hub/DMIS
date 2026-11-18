"""大數據分析群組的樹狀篩選（T-151）：總計 → 品牌 → 能源別 → 車型。

- 只有側欄分組為「大數據分析」的報表使用；其他群組的篩選完全不變。
- 車型層是車種（機種主檔 VehicleModelFamily，T-228）：同一車種的各年式、型號合併成一項，
  不另列型號與年式；勾一項等於勾該車種在報表範圍內的所有車型主檔。
- 網址參數仍是車型主檔（VehicleModel）的 `model`，可重複；全選＝不帶參數，
  全部取消＝`empty_model=1`（不顯示資料），沿用總覽版型「全部取消」的既有口徑。
- 樹的節點只列報表範圍內有資料的車型：報表固定範圍，再取各圖固定範圍的聯集
  （例如車型 X 性別只列 eReady 四個車型圖涵蓋的車型），所以勾選一定影響畫面；
  有來源明細的報表以整份報表範圍為準，明細裡的車型也勾得到。
- 節點台數套用讀者其他篩選（期間、月份、車行…），但不套用樹本身與圖表點選，
  取消勾選的節點仍看得到原本有幾台。
"""
from django.db.models import Count, Q

from sales.models import SalesOrder, VehicleModel

TREE_GROUPS = ("analysis",)
TREE_FIELDS = ("model", "empty_model")
ROOT_KEY = "all"


def tree_enabled(config):
    return (config or {}).get("navigation_group") in TREE_GROUPS


def scope_queryset(config, filters):
    """報表範圍：報表固定範圍 ∩（各圖固定範圍的聯集）。

    有來源明細（明細只套報表固定範圍）或任何一張圖不限車型時，就是整份報表範圍。
    """
    from .engine import base_query
    cards = config.get("cards", [])
    if config.get("include_records") or not cards or any(not card.get("fixed_filters") for card in cards):
        return SalesOrder.objects.filter(pk__in=base_query(config, filters).values("pk"))
    condition = Q()
    for card in cards:
        condition |= Q(pk__in=base_query(config, filters, card).values("pk"))
    return SalesOrder.objects.filter(condition)


def count_filters(filters):
    """節點台數用的條件：讀者其他篩選照套，樹本身、圖表點選與每圖排序不套。"""
    return {key: value for key, value in (filters or {}).items()
            if key not in (*TREE_FIELDS, "focus") and not key.startswith(("_", "sort_", "grain"))}


def selected_models(filters):
    """None＝全選（不限）；空集合＝全部取消。"""
    filters = filters or {}
    if filters.get("empty_model"):
        return set()
    values = filters.get("model") or []
    return {str(value) for value in values} if values else None


def _state(leaves, selected):
    chosen = len(leaves) if selected is None else len(set(leaves) & selected)
    return "checked" if leaves and chosen == len(leaves) else "mixed" if chosen else "unchecked"


def family_key(model):
    """車種歸併依據：機種主檔；沒有機種主檔的舊資料改用品牌＋車型名稱（不分大小寫）。"""
    return model.family_id or f"{model.brand.casefold()}|{model.name.strip().casefold()}"


def family_name(model):
    return model.family.name if model.family_id else model.name


def build_tree(config, filters=None):
    """回傳根節點（總計）。每個節點：key、label、count、state、leaves（車型 pk 字串）、children。

    最末層是車種：leaves 是該車種的所有車型主檔，inputs 是每個主檔的勾選欄位（一起勾、一起取消）。
    根節點另帶 leaf_count（車種數）。
    """
    model_ids = scope_queryset(config, {}).values_list("vehicle_model_id", flat=True).distinct()
    models = list(VehicleModel.objects.filter(pk__in=model_ids).select_related("family"))
    counts = dict(scope_queryset(config, count_filters(filters)).order_by()
                  .values_list("vehicle_model_id").annotate(total=Count("pk")))
    selected = selected_models(filters)
    energy_order = {value: index for index, (value, _) in enumerate(VehicleModel.EnergyType.choices)}
    energy_labels = dict(VehicleModel.EnergyType.choices)
    models.sort(key=lambda model: (model.brand.casefold(), energy_order.get(model.energy_type, 99),
                                   family_name(model).casefold(), model.pk))

    def node(key, label, children=None, leaves=None, level=1):
        leaves = leaves if leaves is not None else [leaf for child in children for leaf in child["leaves"]]
        return {"key": key, "label": label, "detail": "", "level": level, "children": children or [],
                "leaves": leaves, "count": sum(counts.get(int(pk), 0) for pk in leaves),
                "state": _state(leaves, selected)}

    brands = {}
    for model in models:
        (brands.setdefault(model.brand, {}).setdefault(model.energy_type, {})
         .setdefault(family_key(model), []).append(model))
    brand_nodes = []
    leaf_count = 0
    for brand, energies in brands.items():
        energy_nodes = []
        for energy, families in energies.items():
            leaves = []
            for key, items in families.items():
                pks = [str(model.pk) for model in items]
                leaf = node(f"f:{brand}|{energy}|{key}", family_name(items[0]), leaves=pks, level=4)
                leaf["inputs"] = [{"value": pk, "checked": selected is None or pk in selected} for pk in pks]
                leaves.append(leaf)
            leaf_count += len(leaves)
            energy_nodes.append(node(f"e:{brand}|{energy}", energy_labels.get(energy, energy or "未填能源別"),
                                     leaves, level=3))
        brand_nodes.append(node(f"b:{brand}", brand, energy_nodes, level=2))
    root = node(ROOT_KEY, "總計", brand_nodes, level=1)
    root["children_count"] = len(brand_nodes)
    root["leaf_count"] = leaf_count
    return root


def _leaf_nodes(brand):
    return [leaf for energy in brand["children"] for leaf in energy["children"]]


def _leaf_labels(tree):
    """標籤用車種名稱；同一品牌內不同能源別同名時才加能源別區分。"""
    labels = {}
    for brand in tree["children"]:
        names = [leaf["label"].casefold() for leaf in _leaf_nodes(brand)]
        for energy in brand["children"]:
            for leaf in energy["children"]:
                duplicate = names.count(leaf["label"].casefold()) > 1
                labels[leaf["key"]] = leaf["label"] + (f"（{energy['label']}）" if duplicate else "")
    return labels


def _parts(brand, picked, labels):
    """整個能源別都在時寫能源別名稱，否則逐一列車種。picked 是車種節點 key 的集合。"""
    parts = []
    for energy in brand["children"]:
        items = [leaf for leaf in energy["children"] if leaf["key"] in picked]
        if items and len(items) == len(energy["children"]) and len(brand["children"]) > 1:
            parts.append(f"{energy['label']}（全部）")
        else:
            parts.extend(labels[leaf["key"]] for leaf in items)
    return parts


def _summary(values):
    return "、".join(values) if len(values) <= 3 else "、".join(values[:3]) + f" 等 {len(values)} 項"


def tree_chips(tree, filters):
    """目前篩選標籤：每個有限制的品牌一個標籤，移除＝把該品牌恢復全選。

    回傳 [{label, value, title, model, empty}]，model 為移除後的 `model` 參數（None＝不帶）。
    """
    selected = selected_models(filters)
    if selected is None:
        return []
    if not selected:
        text = "未選取（不顯示資料）"
        return [{"label": "車型", "value": text, "title": text, "model": None, "empty": False}]
    all_leaves = set(tree["leaves"])
    labels = _leaf_labels(tree)
    chips = []
    for brand in tree["children"]:
        leaves = set(brand["leaves"])
        if leaves <= selected:
            continue
        # 車種有任一車型主檔被勾就算勾選（舊網址可能只帶某個年式）；一個都沒勾才算取消。
        nodes = _leaf_nodes(brand)
        chosen = {leaf["key"] for leaf in nodes if set(leaf["leaves"]) & selected}
        dropped = {leaf["key"] for leaf in nodes} - chosen
        if not chosen:
            value = "已取消勾選"
        elif dropped and len(dropped) < len(chosen):
            # 大部分還勾著時，列出取消的比較短。
            value = "不含 " + _summary(_parts(brand, dropped, labels))
        else:
            value = _summary(_parts(brand, chosen, labels))
        restored = (selected | leaves) & all_leaves
        model = None if restored == all_leaves else sorted(restored, key=int)
        # title 只放值；active_filters.html 會在前面加上「品牌：」，與其他篩選標籤一致。
        chips.append({"label": brand["label"], "value": value, "title": value,
                      "model": model, "empty": False})
    if not chips:
        # 網址只留下報表範圍外的車型：視同全部取消，提供一個恢復全選的標籤。
        text = "未選取（不顯示資料）"
        chips.append({"label": "車型", "value": text, "title": text, "model": None, "empty": False})
    return chips


# ---- 依勾選車型各一張圖（T-151；T-228 起一個車種一張）----
PER_MODEL_LIMIT = 8  # 與每份報表最多 8 張圖、圖表點選與每圖排序欄位（0–7）一致。


def per_model_template(config):
    cards = (config or {}).get("cards", [])
    return cards[0] if len(cards) == 1 and cards[0].get("per_model") else None


def expand_cards(config, filters=None):
    """把「依勾選車型各一張圖」的範本展開成每個車種一張圖。

    同一車種的各年式、型號合併成一張（T-228，與車型篩選一致），圖卡的 vehicle_model 是該車種的車型主檔清單。
    依台數由多到少（同台數依品牌、車種名稱），最多 PER_MODEL_LIMIT 張；只列有資料的車種。
    台數套用讀者篩選與樹的勾選，但不套圖表點選，展開結果不會因點選圖形而變動。
    回傳 (展開後的報表設定, 說明)；不是範本時原樣回傳、說明為 None。
    """
    template = per_model_template(config)
    if template is None:
        return config, None
    from .engine import base_query
    scope_filters = {key: value for key, value in (filters or {}).items()
                     if key != "focus" and not key.startswith(("_", "sort_", "grain"))}
    counts = list(base_query(config, scope_filters, template).order_by().values("vehicle_model_id")
                  .annotate(total=Count("pk")).values_list("vehicle_model_id", "total"))
    models = VehicleModel.objects.select_related("family").in_bulk([pk for pk, _ in counts])
    groups = {}
    for pk, total in counts:
        model = models[pk]
        group = groups.setdefault(family_key(model), {"name": family_name(model), "brand": model.brand,
                                                      "pks": [], "total": 0})
        group["pks"].append(pk)
        group["total"] += total
    ordered = sorted(groups.values(), key=lambda group: (-group["total"], group["brand"].casefold(),
                                                         group["name"].casefold(), min(group["pks"])))
    shown = ordered[:PER_MODEL_LIMIT]
    names = [group["name"].casefold() for group in shown]
    cards = []
    for group in shown:
        name = group["name"] if names.count(group["name"].casefold()) == 1 else f"{group['name']}（{group['brand']}）"
        card = {key: value for key, value in template.items() if key != "per_model"}
        card.update(title=f"{name}－{template['title']}", vehicle_model=sorted(group["pks"]))
        cards.append(card)
    info = {"total": len(ordered), "shown": len(cards), "hidden": len(ordered) - len(cards), "limit": PER_MODEL_LIMIT}
    return {**config, "cards": cards}, info


def drop_stale_focus(filters, config):
    """展開後圖卡數變少時，移除指向已不存在圖卡的點選，避免整頁查詢失敗。"""
    import json
    from .cross_filter import selections
    chosen = selections((filters or {}).get("focus"))
    kept = [item for item in chosen if item["card"] < len(config["cards"])]
    if len(kept) == len(chosen):
        return filters
    return {**filters, "focus": json.dumps(kept) if kept else ""}
