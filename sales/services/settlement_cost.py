from django.db.models import Q
from django.utils import timezone

from sales.models import OrderOperationsProfile, VehicleSettlementCostRule


def resolve_settlement_cost(vehicle_model_id, registration_date):
    if not vehicle_model_id or not registration_date:
        return None
    return (
        VehicleSettlementCostRule.objects.filter(
            vehicle_model_id=vehicle_model_id,
            active=True,
            effective_from__lte=registration_date,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=registration_date))
        .order_by("-effective_from", "-id")
        .first()
    )


def apply_order_settlement_cost(order, actor_name="", *, lock=False):
    profile, _created = OrderOperationsProfile.objects.get_or_create(order=order)
    if order.zero_vehicle_finance:
        return _zero_non_performance_cost(profile)
    if profile.vehicle_cost_locked_at or profile.vehicle_cost_manual or "vehicle_cost" in (profile.manual_financial_fields or []):
        return profile
    # 尚未領牌：先以訂單日期查成本版本作為「預估」；領牌後依領牌日重新帶入，領牌完成時鎖定。
    basis_date = order.registration_date or order.order_date
    rule = resolve_settlement_cost(order.vehicle_model_id, basis_date)
    if not rule:
        profile.vehicle_cost = 0
        profile.vehicle_cost_rule = None
        profile.vehicle_cost_registration_date = None
        profile.vehicle_cost_manual = False
        profile.save(
            update_fields=[
                "vehicle_cost",
                "vehicle_cost_rule",
                "vehicle_cost_registration_date",
                "vehicle_cost_manual",
                "updated_at",
            ]
        )
        return profile

    profile.vehicle_cost = rule.amount
    profile.vehicle_cost_rule = rule
    profile.vehicle_cost_registration_date = basis_date
    profile.vehicle_cost_manual = False
    update_fields = [
        "vehicle_cost",
        "vehicle_cost_rule",
        "vehicle_cost_registration_date",
        "vehicle_cost_manual",
        "updated_at",
    ]
    if lock:
        profile.vehicle_cost_locked_at = timezone.now()
        profile.vehicle_cost_locked_by = actor_name
        update_fields.extend(["vehicle_cost_locked_at", "vehicle_cost_locked_by"])
    profile.save(update_fields=update_fields)
    return profile


def _zero_non_performance_cost(profile):
    """代交車、中獎車（T-320）：車輛成本固定 0、不依車型帶成本；鎖定與人工覆寫都不保留（收支標「不適用」）。"""
    if profile.vehicle_cost == 0 and profile.vehicle_cost_rule_id is None and not profile.vehicle_cost_manual:
        return profile
    profile.vehicle_cost = 0
    profile.vehicle_cost_rule = None
    profile.vehicle_cost_registration_date = None
    profile.vehicle_cost_manual = False
    profile.save(update_fields=["vehicle_cost", "vehicle_cost_rule", "vehicle_cost_registration_date",
                                "vehicle_cost_manual", "updated_at"])
    return profile


def apply_estimated_settlement_cost(order):
    """尚未領牌的訂單：以訂單日期帶入預估車輛成本；找不到成本版本時不動既有值（不歸零）。"""
    if order.registration_date or not order.vehicle_model_id:
        return None
    profile = OrderOperationsProfile.objects.filter(order=order).first()
    if profile and order.zero_vehicle_finance:
        return _zero_non_performance_cost(profile)
    if not profile or profile.vehicle_cost_locked_at or profile.vehicle_cost_manual or "vehicle_cost" in (profile.manual_financial_fields or []):
        return profile
    if not resolve_settlement_cost(order.vehicle_model_id, order.order_date):
        return profile
    return apply_order_settlement_cost(order)


def vehicle_cost_card_context(order, profile):
    """領牌步驟「車輛結算成本」卡的判斷（訂單頁與自動儲存回應共用，T-331）。

    與「確認領牌完成」同一判斷：人工輸入的成本不會連結規則，不能因此誤報找不到規則。"""
    return {
        "vehicle_cost_is_manual": bool(profile) and (
            profile.vehicle_cost_manual or "vehicle_cost" in (profile.manual_financial_fields or [])
        ),
        "settlement_cost_rule_missing": bool(order.registration_date) and not resolve_settlement_cost(
            order.vehicle_model_id, order.registration_date
        ),
        "vehicle_cost_reset_rule": vehicle_cost_reset_rule(order, profile),
    }


def vehicle_cost_reset_rule(order, profile):
    """收支「改回依規則計算」（T-338）要套用的成本規則；不提供時回 None。

    只給人工輸入的成本，且領牌日（未填用訂單日，與 apply_order_settlement_cost 同一基準）有適用規則；
    代交車、中獎車固定 0，Excel 匯入單是已結算的歷史，都不提供。"""
    if not profile or order.zero_vehicle_finance or hasattr(order, "legacy_snapshot"):
        return None
    if not (profile.vehicle_cost_manual or "vehicle_cost" in (profile.manual_financial_fields or [])):
        return None
    return resolve_settlement_cost(order.vehicle_model_id, order.registration_date or order.order_date)


def reset_vehicle_cost_to_rule(order, actor_name):
    """T-338：清掉人工輸入的車輛成本，重新套用成本規則；已確認領牌的單和確認時一樣固定。

    只動車輛成本與它的來源欄位；淨利、應收、傭金、交車都由既有計算跟著現值算。回傳改前金額，不適用時回 None。"""
    profile = OrderOperationsProfile.objects.filter(order=order).first()
    if vehicle_cost_reset_rule(order, profile) is None:
        return None
    before = profile.vehicle_cost
    profile.manual_financial_fields = sorted(set(profile.manual_financial_fields or []) - {"vehicle_cost"})
    profile.vehicle_cost_manual = False
    profile.vehicle_cost_locked_at = None
    profile.vehicle_cost_locked_by = ""
    profile.save(update_fields=["manual_financial_fields", "vehicle_cost_manual", "vehicle_cost_locked_at",
                                "vehicle_cost_locked_by", "updated_at"])
    apply_order_settlement_cost(order, actor_name, lock=order.is_registration_complete)
    return before
