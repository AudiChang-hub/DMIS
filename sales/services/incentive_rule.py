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


def resolve_incentive_campaigns(vehicle_model, source_type, registration_date, dealer_id=None):
    """依實際領牌日找符合的原廠獎勵活動，回傳 [(活動, {項目: 金額})]（T-161）。

    - 先依通路（都不勾＝暫停）、收款車行、車輛條件過濾。
    - 常態「逐項」取開始日最新的一筆（同一天取 id 較大）：只填實銷的新活動不會蓋掉舊活動的促銷。
    - 加碼全部累加。
    """
    if vehicle_model is None or not registration_date:
        return []
    candidates = active_on(
        IncentiveCampaign.objects.prefetch_related("vehicle_models", "items", "dealers"), registration_date,
    ).select_related("legacy_rule")
    matched = [
        campaign for campaign in candidates
        if campaign.applies_to_source(source_type) and campaign.applies_to_dealer(dealer_id)
        and vehicle_matches(campaign, vehicle_model)
    ]
    regulars = sorted((c for c in matched if c.kind == IncentiveCampaign.Kind.REGULAR), key=lambda c: c.pk)
    chosen = {}
    for field_name in INCENTIVE_FIELDS:
        having = [campaign for campaign in regulars if field_name in campaign.item_amounts()]
        if having:
            best = max(having, key=lambda campaign: (campaign.effective_from, campaign.pk))
            chosen.setdefault(best, {})[field_name] = best.item_amounts()[field_name]
    rows = [(campaign, chosen[campaign]) for campaign in regulars if campaign in chosen]
    for campaign in sorted((c for c in matched if c.kind == IncentiveCampaign.Kind.BONUS), key=lambda c: c.pk):
        amounts = campaign.item_amounts()
        if amounts:
            rows.append((campaign, amounts))
    return [
        (campaign, {field_name: amounts.get(field_name, Decimal("0")) for field_name in INCENTIVE_FIELDS}, set(amounts))
        for campaign, amounts in rows
    ]


def incentive_totals(vehicle_model, source_type, registration_date, dealer_id=None):
    """回傳 (各活動明細, 合計, 是否有符合的活動, 是否有活動給促銷, 第一筆常態)。"""
    resolved = resolve_incentive_campaigns(vehicle_model, source_type, registration_date, dealer_id)
    rows = [(campaign, amounts) for campaign, amounts, _given in resolved]
    totals = {
        field_name: sum((amounts[field_name] for _campaign, amounts in rows), Decimal("0"))
        for field_name in INCENTIVE_FIELDS
    }
    promotion_applies = any("promotion_subsidy" in given for _campaign, _amounts, given in resolved)
    regular = next((campaign for campaign, _amounts in rows if campaign.kind == IncentiveCampaign.Kind.REGULAR), None)
    return rows, totals, bool(rows), promotion_applies, regular


def apply_order_incentive_rule(order, actor_name="", *, lock=False):
    profile, _created = OrderOperationsProfile.objects.get_or_create(order=order)
    if profile.incentive_locked_at:
        return profile

    from sales.services.dealer_reward_campaign import order_reward_dealer

    vehicle_model = order.vehicle_model if order.vehicle_model_id else None
    dealer = order_reward_dealer(order)
    rows, totals, matched, promotion_applies, regular = incentive_totals(
        vehicle_model, order.source_type, order.registration_date, dealer.pk if dealer else None,
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
            # 沒有符合的活動帶 0；通路、車行由活動決定，仍可人工更正。
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
    replace_incentive_applications(profile, rows, order.registration_date)
    return profile


def replace_incentive_applications(profile, rows, registration_date):
    """訂單套用的活動明細整批換成這次的結果（明細存當時金額，之後改活動不影響）。"""
    profile.incentive_applications.all().delete()
    OrderIncentiveApplication.objects.bulk_create([
        OrderIncentiveApplication(
            profile=profile,
            campaign=campaign,
            kind=campaign.kind,
            campaign_name=campaign.name,
            registration_date=registration_date,
            **amounts,
        )
        for campaign, amounts in rows
    ])
