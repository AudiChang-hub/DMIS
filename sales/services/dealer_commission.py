from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from sales.models import (
    DealerVolumeBonusAdjustment,
    DealerVolumeBonusAllocation,
    DealerVolumeBonusSettlement,
    OrderOperationsProfile,
    SalesOrder,
    SalesSource,
    SalesSourceBrandPolicy,
)


def resolve_dealer_brand_policy(source_id, brand, effective_date):
    if not source_id or not brand or not effective_date:
        return None
    return (
        SalesSourceBrandPolicy.objects.filter(
            source_id=source_id,
            source__source_type=SalesSource.SourceType.DEALER,
            brand__iexact=brand,
            cooperates=True,
            effective_from__lte=effective_date,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=effective_date))
        .order_by("-effective_from", "-id")
        .first()
    )


def dealer_volume_bonus_total(order):
    return order.dealer_volume_bonus_allocations.aggregate(total=Sum("amount"))[
        "total"
    ] or Decimal("0")


def apply_order_dealer_commission(order, *, lock=False):
    profile, _ = OrderOperationsProfile.objects.get_or_create(order=order)
    if order.source_type != SalesOrder.SourceType.DEALER or not order.source_id:
        if "dealer_commission_expense" not in profile.manual_financial_fields:
            profile.dealer_commission_base = 0
            profile.dealer_commission_adjustment = 0
            profile.dealer_commission_policy = None
            profile.dealer_commission_registration_date = order.registration_date
            profile.dealer_commission_expense = dealer_volume_bonus_total(order)
        profile.save()
        return profile

    effective_date = order.registration_date or order.order_date
    policy = resolve_dealer_brand_policy(
        order.source_id, order.vehicle_model.brand, effective_date
    )
    base = order.vehicle_model.base_dealer_commission or Decimal("0")
    adjustment = policy.commission_adjustment if policy else Decimal("0")
    if "dealer_commission_expense" not in profile.manual_financial_fields:
        profile.dealer_commission_base = base
        profile.dealer_commission_adjustment = adjustment
        profile.dealer_commission_policy = policy
        profile.dealer_commission_registration_date = effective_date
        profile.dealer_commission_expense = (
            base + adjustment + dealer_volume_bonus_total(order)
        )
    if lock:
        profile.dealer_commission_locked_at = timezone.now()
    profile.save()
    return profile


def eligible_volume_bonus_orders(rule):
    return (
        SalesOrder.objects.filter(
            source=rule.dealer,
            vehicle_model__brand__iexact=rule.brand,
            registration_date__range=(rule.starts_on, rule.ends_on),
            registration_completed_at__isnull=False,
        )
        .exclude(status=SalesOrder.Status.CANCELLED)
        .select_related("vehicle_model", "source")
        .order_by("registration_date", "number")
    )


def preview_volume_bonus(rule):
    orders = list(eligible_volume_bonus_orders(rule))
    tier = rule.tiers.filter(minimum_quantity__lte=len(orders)).order_by(
        "-minimum_quantity"
    ).first()
    per_vehicle = tier.bonus_per_vehicle if tier else Decimal("0")
    return {
        "orders": orders,
        "quantity": len(orders),
        "tier": tier,
        "bonus_per_vehicle": per_vehicle,
        "expected_amount": per_vehicle * len(orders),
    }


def _allocation_amounts(total, count):
    if not count:
        return []
    integer_total = int(total)
    base, remainder = divmod(integer_total, count)
    return [Decimal(base + (1 if index < remainder else 0)) for index in range(count)]


@transaction.atomic
def create_volume_bonus_settlement(rule, actor_name, actual_amount=None, reason=""):
    if hasattr(rule, "settlement"):
        raise ValueError("此規則已完成結算，不可重複建立。")
    preview = preview_volume_bonus(rule)
    if not preview["tier"]:
        raise ValueError("目前符合台數尚未達到任何獎金門檻。")
    expected = preview["expected_amount"]
    actual = expected if actual_amount is None else Decimal(actual_amount)
    settlement = DealerVolumeBonusSettlement.objects.create(
        rule=rule,
        qualified_quantity=preview["quantity"],
        bonus_per_vehicle=preview["bonus_per_vehicle"],
        expected_amount=expected,
        actual_amount=actual,
        adjustment_reason=reason,
        settled_by=actor_name,
    )
    amounts = _allocation_amounts(actual, len(preview["orders"]))
    DealerVolumeBonusAllocation.objects.bulk_create(
        [
            DealerVolumeBonusAllocation(
                settlement=settlement,
                order=order,
                amount=amount,
            )
            for order, amount in zip(preview["orders"], amounts)
        ]
    )
    for order in preview["orders"]:
        apply_order_dealer_commission(order)
    return settlement


@transaction.atomic
def revise_volume_bonus_settlement(settlement, actor_name, actual_amount, reason):
    settlement = (
        DealerVolumeBonusSettlement.objects.select_for_update()
        .prefetch_related("allocations__order")
        .get(pk=settlement.pk)
    )
    revised = Decimal(actual_amount)
    reason = (reason or "").strip()
    if revised == settlement.actual_amount:
        raise ValueError("實際金額沒有變更。")
    if not reason:
        raise ValueError("調整已結算金額時必須填寫原因。")

    previous = settlement.actual_amount
    allocations = list(settlement.allocations.select_related("order"))
    amounts = _allocation_amounts(revised, len(allocations))
    updated_at = timezone.now()
    for allocation, amount in zip(allocations, amounts):
        allocation.amount = amount
        allocation.updated_at = updated_at
    DealerVolumeBonusAllocation.objects.bulk_update(allocations, ["amount", "updated_at"])

    settlement.actual_amount = revised
    settlement.adjustment_reason = reason
    settlement.save(update_fields=["actual_amount", "adjustment_reason", "updated_at"])
    DealerVolumeBonusAdjustment.objects.create(
        settlement=settlement,
        previous_amount=previous,
        revised_amount=revised,
        reason=reason,
        adjusted_by=actor_name,
    )
    for allocation in allocations:
        apply_order_dealer_commission(allocation.order)
    return settlement
