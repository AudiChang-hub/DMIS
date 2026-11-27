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
