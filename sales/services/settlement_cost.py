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
    if profile.vehicle_cost_locked_at:
        return profile
    rule = resolve_settlement_cost(
        order.vehicle_model_id,
        order.registration_date,
    )
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
    profile.vehicle_cost_registration_date = order.registration_date
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
