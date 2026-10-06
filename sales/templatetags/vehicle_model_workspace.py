"""機種工作區：同一年式的規格、售價、分期、傭金、成本、獎勵與選車展示共用一組頁首與分頁。"""
from django import template
from django.urls import reverse
from django.utils import timezone

from sales.access.services import policy_for

register = template.Library()

# (分頁代號, 名稱, 路由, 路由參數名稱, 版本數量的關聯名稱)
TABS = (
    ("spec", "規格與車色", "vehicle_model_edit", "pk", ""),
    ("prices", "售價", "vehicle_model_price_versions", "model_pk", "price_versions"),
    ("installments", "分期", "vehicle_installment_plan_list", "model_pk", "installment_plan_versions"),
    ("commission", "傭金與獎勵", "vehicle_model_commission", "model_pk", "dealer_reward_plans"),
    ("costs", "結算成本", "vehicle_model_settlement_costs", "model_pk", "settlement_cost_rules"),
    ("incentives", "原廠獎勵與補助", "vehicle_model_incentives", "model_pk", "incentive_rules"),
    ("catalog", "選車圖片與介紹", "catalog_edit", "pk", ""),
    ("rules", "適用規則", "vehicle_model_rules", "model_pk", ""),
)
UNSAVED_HINT = "儲存後即可設定"
INACTIVE_CATALOG_HINT = "機種啟用後才能編輯選車展示"


def _brand_tone(brand):
    value = (brand or "").upper()
    if "SYM" in value or "三陽" in value:
        return "sym"
    if "SUZUKI" in value or "台鈴" in value:
        return "suzuki"
    return "neutral"


def _power_label(vehicle_model):
    if vehicle_model.energy_type == vehicle_model.EnergyType.GAS:
        return f"{vehicle_model.displacement_cc} c.c." if vehicle_model.displacement_cc else "排氣量待補"
    parts = []
    if vehicle_model.motor_power_kw is not None:
        parts.append(f"{vehicle_model.motor_power_kw.normalize():f} kW")
    if vehicle_model.electric_registration_class:
        parts.append(vehicle_model.get_electric_registration_class_display())
    return "・".join(parts) or "規格待補"


def _back_target(context, policy):
    override = context.get("workspace_back")
    if override:
        return override
    for route, label in (
        ("vehicle_model_list", "機種與售價"),
        ("dealer_sales_program_list", "車行傭金與銷售獎勵"),
    ):
        if policy.route(route):
            return reverse(route), label
    return reverse("data_maintenance"), "資料維護區"


STATUS_UNITS = {
    "prices": "售價版本", "installments": "分期方案版本", "costs": "成本版本", "incentives": "獎勵版本",
}


def _apply_status(tab, vehicle_model, price_missing):
    """分頁只標示已設定／未設定，細節放在提示文字，避免把版本數誤認為金額或筆數。"""
    count = tab["count"]
    if tab["key"] == "commission":
        base = vehicle_model.base_dealer_commission or 0
        configured = base > 0 or count > 0
        tab["detail"] = f"基礎傭金 {base:,.0f} 元；附加獎勵 {count} 個版本"
    else:
        configured = count > 0
        tab["detail"] = f"{count} 個{STATUS_UNITS.get(tab['key'], '版本')}"
        if tab["key"] == "prices" and price_missing:
            tab["detail"] += "；今天沒有有效售價"
    tab["status"] = "set" if configured else "unset"


@register.simple_tag(takes_context=True)
def vehicle_model_workspace(context, vehicle_model, active):
    request = context["request"]
    policy = policy_for(request)
    saved = bool(vehicle_model is not None and vehicle_model.pk)
    tabs = []
    for key, label, route, kwarg, related in TABS:
        if key != active and not policy.route(route):
            continue
        tab = {"key": key, "label": label, "current": key == active, "url": "", "hint": "", "count": None,
               "status": "", "detail": ""}
        if not saved:
            tab["hint"] = "" if key == "spec" else UNSAVED_HINT
        elif key == "catalog" and not vehicle_model.active:
            tab["hint"] = INACTIVE_CATALOG_HINT
        if saved and not tab["hint"]:
            tab["url"] = reverse(route, kwargs={kwarg: vehicle_model.pk})
            if related:
                tab["count"] = getattr(vehicle_model, related).count()
        tabs.append(tab)
    price_missing = False
    if saved and any(tab["key"] == "prices" for tab in tabs):
        from sales.services.price_version import resolve_vehicle_price_version

        price_missing = resolve_vehicle_price_version(vehicle_model.pk, timezone.localdate()) is None
    for tab in tabs:
        tab["attention"] = tab["key"] == "prices" and price_missing
        if tab["count"] is not None:
            _apply_status(tab, vehicle_model, price_missing)
    back_url, back_label = _back_target(context, policy)
    current = next((tab for tab in tabs if tab["current"]), None)
    return {
        "saved": saved,
        "tabs": tabs,
        "current_label": current["label"] if current else "",
        "back_url": back_url,
        "back_label": back_label,
        "price_missing": price_missing,
        "has_disabled": any(tab["hint"] for tab in tabs),
        "brand_tone": _brand_tone(vehicle_model.brand) if saved else "neutral",
        "power_label": _power_label(vehicle_model) if saved else "",
    }
