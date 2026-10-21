from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from sales.models import OrderOperationsProfile, VehicleIncentiveRule, VehicleModel


INCENTIVE_FIELDS = (
    "sales_bonus",
    "promotion_subsidy",
    "installment_interest_subsidy",
)

# 強制險傭金（使用者 2026-10-15）：油車與電動車依強制險年期固定金額；微型電動二輪車另計，不自動帶入。
COMPULSORY_INSURANCE_COMMISSION = {1: Decimal("145"), 2: Decimal("215")}


def compulsory_insurance_commission(order):
    """回傳應帶入的強制險傭金；None 表示此訂單不套用固定規則。"""
    vehicle_model = order.vehicle_model if order.vehicle_model_id else None
    if vehicle_model is None or vehicle_model.energy_type == VehicleModel.EnergyType.MICRO_ELECTRIC:
        return None
    return COMPULSORY_INSURANCE_COMMISSION.get(order.compulsory_insurance_period)


def _calculated_disbursement(order):
    """實際車價收入的預設（使用者 2026-10-21 T-62）：現金單＝車價；分期單＝分期那筆×撥款比例（方案快照的預估撥款）
    ＋現金／刷卡／匯款各筆全額。分期部分算不出來時不帶，維持人工填寫。"""
    if order.source_type == order.SourceType.PLATFORM:
        return None
    if order.payment_type == order.PaymentType.CASH:
        return order.vehicle_price or Decimal("0")
    if order.payment_type == order.PaymentType.INSTALLMENT:
        snapshot = order.installment_plan_snapshot or {}
        amount = snapshot.get("expected_disbursement_amount")
        if amount is None:
            return None
        return Decimal(str(amount)) + order.customer_vehicle_split_amount
    return None


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
            value = getattr(rule, field_name) if rule else 0
            # 促銷補助金只有網路平台訂單才有；其他來源帶 0，仍可人工更正。
            if field_name == "promotion_subsidy" and order.source_type != order.SourceType.PLATFORM:
                value = 0
            setattr(profile, field_name, value)
    insurance_commission = compulsory_insurance_commission(order)
    if insurance_commission is not None and "insurance_commission" not in protected_fields:
        profile.insurance_commission = insurance_commission
    calculated_disbursement = _calculated_disbursement(order)
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
    profile.incentive_registration_date = (
        order.registration_date if rule else None
    )
    update_fields = [
        *INCENTIVE_FIELDS,
        "insurance_commission",
        "actual_disbursement",
        "incentive_rule",
        "incentive_registration_date",
        "updated_at",
    ]
    if lock:
        profile.incentive_locked_at = timezone.now()
        profile.incentive_locked_by = actor_name
        update_fields.extend(["incentive_locked_at", "incentive_locked_by"])
    profile.save(update_fields=update_fields)
    return profile
