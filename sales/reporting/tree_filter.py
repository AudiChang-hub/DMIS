"""大數據分析群組的樹狀篩選（T-151）：總計 → 品牌 → 能源別 → 車型。

- 只有側欄分組為「大數據分析」的報表使用；其他群組的篩選完全不變。
- 車型層是訂單的車型主檔（VehicleModel），網址參數 `model` 可重複；全選＝不帶參數，
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


def model_label(model):
    secondary = [value for value in (model.model_number if model.model_number != model.name else "",
                                     str(model.model_year) if model.model_year else "") if value]
    return model.name, " · ".join(secondary)


def build_tree(config, filters=None):
    """回傳根節點（總計）。每個節點：key、label、detail、count、state、leaves（車型 pk 字串）、children。"""
    model_ids = scope_queryset(config, {}).values_list("vehicle_model_id", flat=True).distinct()
    models = list(VehicleModel.objects.filter(pk__in=model_ids))
    counts = dict(scope_queryset(config, count_filters(filters)).order_by()
                  .values_list("vehicle_model_id").annotate(total=Count("pk")))
    selected = selected_models(filters)
    energy_order = {value: index for index, (value, _) in enumerate(VehicleModel.EnergyType.choices)}
    energy_labels = dict(VehicleModel.EnergyType.choices)
    models.sort(key=lambda model: (model.brand.casefold(), energy_order.get(model.energy_type, 99),
                                   model.name.casefold(), model.model_number, model.model_year or 0, model.pk))

    def node(key, label, children=None, leaves=None, detail="", level=1):
        leaves = leaves if leaves is not None else [leaf for child in children for leaf in child["leaves"]]
        return {"key": key, "label": label, "detail": detail, "level": level, "children": children or [],
                "leaves": leaves, "count": sum(counts.get(int(pk), 0) for pk in leaves),
                "state": _state(leaves, selected)}

    brands = {}
    for model in models:
        brands.setdefault(model.brand, {}).setdefault(model.energy_type, []).append(model)
    brand_nodes = []
    for brand, energies in brands.items():
        energy_nodes = []
        for energy, items in energies.items():
            leaves = []
            for model in items:
                name, detail = model_label(model)
                leaves.append(node(f"m:{model.pk}", name, leaves=[str(model.pk)], detail=detail, level=4))
            energy_nodes.append(node(f"e:{brand}|{energy}", energy_labels.get(energy, energy or "未填能源別"),
                                     leaves, level=3))
        brand_nodes.append(node(f"b:{brand}", brand, energy_nodes, level=2))
    root = node(ROOT_KEY, "總計", brand_nodes, level=1)
    root["children_count"] = len(brand_nodes)
    return root


def _leaf_labels(tree):
    """標籤用車型名稱；同一品牌內同名時才加型號／年式區分。"""
    labels = {}
    for brand in tree["children"]:
        leaves = [leaf for energy in brand["children"] for leaf in energy["children"]]
        names = [leaf["label"] for leaf in leaves]
        for leaf in leaves:
            duplicate = names.count(leaf["label"]) > 1 and leaf["detail"]
            labels[leaf["leaves"][0]] = leaf["label"] + (f"（{leaf['detail']}）" if duplicate else "")
    return labels


def _parts(brand, picked, labels):
    """整個能源別都在時寫能源別名稱，否則逐一列車型。"""
    parts = []
    for energy in brand["children"]:
        items = [leaf for leaf in energy["leaves"] if leaf in picked]
        if items and len(items) == len(energy["leaves"]) and len(brand["children"]) > 1:
            parts.append(f"{energy['label']}（全部）")
        else:
            parts.extend(labels[leaf] for leaf in items)
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
        chosen = leaves & selected
        if chosen == leaves:
            continue
        if not chosen:
            value = "已取消勾選"
        elif len(leaves - chosen) < len(chosen):
            # 大部分還勾著時，列出取消的比較短。
            value = "不含 " + _summary(_parts(brand, leaves - chosen, labels))
        else:
            value = _summary(_parts(brand, chosen, labels))
        restored = (selected | leaves) & all_leaves
        model = None if restored == all_leaves else sorted(restored, key=int)
        chips.append({"label": brand["label"], "value": value, "title": brand["label"] + "：" + value,
                      "model": model, "empty": False})
    if not chips:
        # 網址只留下報表範圍外的車型：視同全部取消，提供一個恢復全選的標籤。
        text = "未選取（不顯示資料）"
        chips.append({"label": "車型", "value": text, "title": text, "model": None, "empty": False})
    return chips
