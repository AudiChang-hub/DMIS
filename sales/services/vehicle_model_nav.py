"""機種工作區左側的機種清單。

排列與「機種與售價」列表一致：主品牌依品牌排序，主品牌自己的機種在上，子品牌依名稱往下；
每個機種列出各年式。點年式會停在同一個分頁；沒有該分頁權限（或停用機種的選車展示）時，
改到該機種可用的第一個分頁。停用的機種排在每個品牌段落的最後。
"""
from django.urls import reverse

from sales.models import VehicleBrand, VehicleModel
from sales.services.vehicle_brands import brand_tree_sort_key

ELECTRIC_TYPES = {
    VehicleModel.EnergyType.ELECTRIC,
    VehicleModel.EnergyType.LIGHT_ELECTRIC,
    VehicleModel.EnergyType.MICRO_ELECTRIC,
}


def _power_key(model):
    if model.energy_type in ELECTRIC_TYPES:
        return (0, model.motor_power_kw is None, model.motor_power_kw or 0)
    if model.energy_type == VehicleModel.EnergyType.GAS:
        return (1, model.displacement_cc is None, model.displacement_cc or 0)
    return (2, True, 0)


def _target_url(model, active_tab, tabs, policy):
    """同一分頁優先；不能用時改到這台機種可用的第一個分頁。"""
    usable = [
        (key, route, kwarg)
        for key, _label, route, kwarg, _related in tabs
        if policy.route(route) and not (key == "catalog" and not model.active)
    ]
    for key, route, kwarg in usable:
        if key == active_tab:
            return reverse(route, kwargs={kwarg: model.pk})
    if usable:
        _key, route, kwarg = usable[0]
        return reverse(route, kwargs={kwarg: model.pk})
    return ""


def build_model_navigator(current_model, active_tab, tabs, policy):
    brands = {brand.name.casefold(): brand for brand in VehicleBrand.objects.select_related("parent")}
    models = VehicleModel.objects.select_related("family").order_by("brand", "name", "-model_year", "model_code", "pk")

    roots = {}
    for model in models:
        url = _target_url(model, active_tab, tabs, policy)
        if not url:
            continue
        record = brands.get(model.brand.casefold())
        root = record.parent if record and record.parent_id else record
        root_name = root.name if root else model.brand
        root_entry = roots.setdefault(root_name.casefold(), {
            "name": root_name,
            "sort": brand_tree_sort_key(root) if root else (999, root_name.casefold(), 0, 0, 0, ""),
            "sections": {},
        })
        sub_label = model.brand if model.brand.casefold() != root_name.casefold() else ""
        section = root_entry["sections"].setdefault(sub_label.casefold(), {"label": sub_label, "families": {}})
        family_name = model.family.name if model.family_id else model.name
        family_key = model.family_id or f"legacy:{model.brand.casefold()}:{family_name.casefold()}"
        family = section["families"].setdefault(family_key, {"name": family_name, "models": []})
        family["models"].append({"model": model, "url": url})

    groups = []
    for root in sorted(roots.values(), key=lambda item: item["sort"]):
        sections = []
        model_count = 0
        # 主品牌自己的機種（label 空白）排最上方，子品牌依名稱往下。
        for section in sorted(root["sections"].values(), key=lambda item: (bool(item["label"]), item["label"].casefold())):
            families = []
            for family in section["families"].values():
                entries = sorted(
                    family["models"],
                    key=lambda item: (not item["model"].active, -(item["model"].model_year or 0),
                                      item["model"].model_code, item["model"].pk),
                )
                year_counts = {}
                for item in entries:
                    year_counts[item["model"].model_year] = year_counts.get(item["model"].model_year, 0) + 1
                years = []
                for item in entries:
                    model = item["model"]
                    label = str(model.model_year) if model.model_year else "年式待補"
                    if year_counts[model.model_year] > 1 and model.model_code:
                        label += f" {model.get_model_code_display()}"  # 同年式有多個型式時才補型式
                    years.append({
                        "pk": model.pk, "label": label, "url": item["url"], "active": model.active,
                        "current": current_model is not None and model.pk == current_model.pk,
                    })
                lead = entries[0]["model"]
                search = " ".join(filter(None, [
                    root["name"], section["label"], family["name"],
                    *{entry["model"].name for entry in entries},
                    *{entry["model"].model_number for entry in entries},
                    *{str(entry["model"].model_year or "") for entry in entries},
                ])).casefold()
                families.append({
                    "name": family["name"],
                    "years": years,
                    "active": any(entry["active"] for entry in years),
                    "current": any(entry["current"] for entry in years),
                    "search": search,
                    "sort": (not any(entry["active"] for entry in years), _power_key(lead), family["name"].casefold()),
                })
            families.sort(key=lambda item: item["sort"])
            model_count += sum(len(family["years"]) for family in families)
            sections.append({"label": section["label"], "families": families, "inactive": False})
        # 停用的機種與「機種與售價」列表一致：統一放在這個品牌的最後一段。
        retired = [family for section in sections for family in section["families"] if not family["active"]]
        sections = [
            {**section, "families": [family for family in section["families"] if family["active"]]}
            for section in sections
        ]
        sections = [section for section in sections if section["families"]]
        if retired:
            sections.append({"label": "已停用", "families": retired, "inactive": True})
        groups.append({
            "name": root["name"],
            "sections": sections,
            "count": model_count,
            "current": any(family["current"] for section in sections for family in section["families"]),
        })
    return groups
