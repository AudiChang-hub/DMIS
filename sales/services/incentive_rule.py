from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q
from django.utils import timezone

from sales.models import OrderOperationsProfile, VehicleIncentiveRule


INCENTIVE_FIELDS = (
    "sales_bonus",
    "promotion_subsidy",
    "installment_interest_subsidy",
)


def _calculated_disbursement(order, rule):
    if order.source_type == order.SourceType.PLATFORM:
        return None, None
    if order.payment_type == order.PaymentType.CASH:
        return order.vehicle_price or Decimal("0"), None
    if order.payment_type == order.PaymentType.INSTALLMENT and rule:
        rate_rule = rule.installment_rates.filter(
            periods=order.installment_periods
        ).first()
        if not rate_rule:
            return None, None
        amount = (
            (order.vehicle_price or Decimal("0"))
            * rate_rule.rate
            / Decimal("100")
        ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        snapshot = order.installment_plan_snapshot or {}
        amount += Decimal(str(snapshot.get("extra_disbursement_bonus") or 0))
        return amount, rate_rule
    return None, None


def resolve_incentive_rule(vehicle_model_id, registration_date):
    if not vehicle_model_id or not registration_date:
        return None
    return (
        VehicleIncentiveRule.objects.filter(
            vehicle_model_id=vehicle_model_id,
            active=True,
            effective_from__lte=registration_date,
        )
        .filter(
            Q(effective_to__isnull=True)
            | Q(effective_to__gte=registration_date)
        )
        .order_by("-effective_from", "-id")
        .first()
    )


def apply_order_incentive_rule(order, actor_name="", *, lock=False):
    profile, _created = OrderOperationsProfile.objects.get_or_create(order=order)
    if profile.incentive_locked_at:
        return profile

    rule = resolve_incentive_rule(
        order.vehicle_model_id,
        order.registration_date,
    )
    protected_fields = set(profile.manual_financial_fields or [])
    for field_name in INCENTIVE_FIELDS:
        if field_name not in protected_fields:
            setattr(profile, field_name, getattr(rule, field_name) if rule else 0)
    calculated_disbursement, installment_rate_rule = _calculated_disbursement(
        order,
        rule,
    )
    if (
        calculated_disbursement is not None
        and "actual_disbursement" not in protected_fields
    ):
        profile.actual_disbursement = calculated_disbursement
    elif (
        order.payment_type == order.PaymentType.INSTALLMENT
        and order.source_type != order.SourceType.PLATFORM
        and "actual_disbursement" not in protected_fields
    ):
        profile.actual_disbursement = 0

    profile.incentive_rule = rule
    profile.incentive_installment_rate_rule = installment_rate_rule
    profile.incentive_installment_periods = (
        order.installment_periods
        if order.payment_type == order.PaymentType.INSTALLMENT
        else None
    )
    profile.incentive_installment_rate = (
        installment_rate_rule.rate if installment_rate_rule else None
    )
    profile.incentive_registration_date = (
        order.registration_date if rule else None
    )
    update_fields = [
        *INCENTIVE_FIELDS,
        "actual_disbursement",
        "incentive_rule",
        "incentive_installment_rate_rule",
        "incentive_installment_periods",
        "incentive_installment_rate",
        "incentive_registration_date",
        "updated_at",
    ]
    if lock:
        profile.incentive_locked_at = timezone.now()
        profile.incentive_locked_by = actor_name
        update_fields.extend(["incentive_locked_at", "incentive_locked_by"])
    profile.save(update_fields=update_fields)
    return profile
