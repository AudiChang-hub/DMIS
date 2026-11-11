from decimal import Decimal

from django.utils import timezone

from sales.models import IncentiveCampaign, OrderIncentiveApplication, OrderOperationsProfile, VehicleModel
from sales.services.campaign_conditions import active_on, vehicle_matches


INCENTIVE_FIELDS = (
    "sales_bonus",
    "promotion_subsidy",
    "installment_interest_subsidy",
)

# 強制險傭金（使用者 2026-10-15）：油車、電動車、輕型電動車依強制險年期一年 145、兩年 215，沒有其他分級。
COMPULSORY_INSURANCE_COMMISSION = {1: Decimal("145"), 2: Decimal("215")}
# 微型電動二輪車強制險一律三年，傭金固定 100（UAT p6，使用者 2026-11-06 選 A），不看訂單填的年期。
MICRO_ELECTRIC_COMPULSORY_INSURANCE_COMMISSION = Decimal("100")


def compulsory_insurance_commission(order):
    """回傳應帶入的強制險傭金；None 表示此訂單不套用固定規則。"""
    vehicle_model = order.vehicle_model if order.vehicle_model_id else None
    if vehicle_model is None:
        return None
    if vehicle_model.energy_type == VehicleModel.EnergyType.MICRO_ELECTRIC:
        return MICRO_ELECTRIC_COMPULSORY_INSURANCE_COMMISSION
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


def resolve_incentive_campaigns(vehicle_model, source_type, registration_date):
    """依實際領牌日找符合的原廠獎勵活動（T-149）：回傳 (常態, [加碼])。

    常態取開始日最新的一筆（與原本車型版本相同，新的蓋過舊的）；加碼全部累加。
    """
    if vehicle_model is None or not registration_date:
        return None, []
    candidates = active_on(
        IncentiveCampaign.objects.prefetch_related("vehicle_models"), registration_date,
    ).select_related("legacy_rule")
    matched = [
        campaign for campaign in candidates
        if campaign.applies_to_source(source_type) and vehicle_matches(campaign, vehicle_model)
    ]
    regulars = [campaign for campaign in matched if campaign.kind == IncentiveCampaign.Kind.REGULAR]
    regular = max(regulars, key=lambda campaign: (campaign.effective_from, campaign.pk)) if regulars else None
    bonuses = sorted(
        (campaign for campaign in matched if campaign.kind == IncentiveCampaign.Kind.BONUS),
        key=lambda campaign: campaign.pk,
    )
    return regular, bonuses


def campaign_amounts(campaign, source_type):
    """單一活動帶給這張單的金額；促銷補助只給活動勾選的通路。"""
    return {
        "sales_bonus": campaign.sales_bonus,
        "promotion_subsidy": campaign.promotion_subsidy if campaign.gives_promotion_to(source_type) else Decimal("0"),
        "installment_interest_subsidy": campaign.installment_interest_subsidy,
    }


def incentive_totals(vehicle_model, source_type, registration_date):
    """回傳 (各活動明細, 合計, 是否有符合的活動, 會帶入促銷的活動是否存在)。"""
    regular, bonuses = resolve_incentive_campaigns(vehicle_model, source_type, registration_date)
    campaigns = ([regular] if regular else []) + bonuses
    rows = [(campaign, campaign_amounts(campaign, source_type)) for campaign in campaigns]
    totals = {
        field_name: sum((amounts[field_name] for _campaign, amounts in rows), Decimal("0"))
        for field_name in INCENTIVE_FIELDS
    }
    promotion_applies = any(campaign.gives_promotion_to(source_type) for campaign in campaigns)
    return rows, totals, bool(campaigns), promotion_applies, regular


def apply_order_incentive_rule(order, actor_name="", *, lock=False):
    profile, _created = OrderOperationsProfile.objects.get_or_create(order=order)
    if profile.incentive_locked_at:
        return profile

    vehicle_model = order.vehicle_model if order.vehicle_model_id else None
    rows, totals, matched, promotion_applies, regular = incentive_totals(
        vehicle_model, order.source_type, order.registration_date,
    )
    protected_fields = set(profile.manual_financial_fields or [])
    released = set()
    if matched:
        # 領牌日期前先手動填了獎勵（T-120 p13）：找到活動後，人工值與活動合計相同的欄位改回「系統帶入」，
        # 之後隨活動更新；金額不同的人工值照舊保留、不覆寫。
        for field_name in INCENTIVE_FIELDS:
            if field_name == "promotion_subsidy" and not promotion_applies:
                continue
            if field_name in protected_fields and getattr(profile, field_name) == totals[field_name]:
                released.add(field_name)
        protected_fields -= released
    for field_name in INCENTIVE_FIELDS:
        if field_name not in protected_fields:
            # 沒有符合的活動帶 0；促銷補助只給活動勾選的通路（預設只有網路平台），仍可人工更正。
            setattr(profile, field_name, totals[field_name])
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

    # 舊欄位保留給回切舊版：常態活動由車型版本轉換而來時指回該版本。
    profile.incentive_rule = regular.legacy_rule if regular else None
    profile.incentive_registration_date = order.registration_date if matched else None
    update_fields = [
        *INCENTIVE_FIELDS,
        "insurance_commission",
        "actual_disbursement",
        "incentive_rule",
        "incentive_registration_date",
        "updated_at",
    ]
    if released:
        profile.manual_financial_fields = sorted(set(profile.manual_financial_fields or []) - released)
        update_fields.append("manual_financial_fields")
    if lock:
        profile.incentive_locked_at = timezone.now()
        profile.incentive_locked_by = actor_name
        update_fields.extend(["incentive_locked_at", "incentive_locked_by"])
    profile.save(update_fields=update_fields)
    profile.incentive_applications.all().delete()
    OrderIncentiveApplication.objects.bulk_create([
        OrderIncentiveApplication(
            profile=profile,
            campaign=campaign,
            kind=campaign.kind,
            campaign_name=campaign.name,
            registration_date=order.registration_date,
            **amounts,
        )
        for campaign, amounts in rows
    ])
    return profile
