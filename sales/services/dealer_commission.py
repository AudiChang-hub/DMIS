from decimal import Decimal

from django.db import transaction
from django.db.models import Exists, OuterRef, Q, Sum
from django.utils import timezone

from sales.models import (
    DealerVolumeBonusAdjustment,
    DealerVolumeBonusAllocation,
    DealerVolumeBonusRule,
    DealerVolumeBonusSettlement,
    OrderOperationsProfile,
    SalesOrder,
    SalesSource,
    SalesSourceBrandPolicy,
    VehicleBrand,
    VehicleModel,
)


def cooperation_scope_for_vehicle_model(vehicle_model):
    """Map a vehicle model to the dealer cooperation category used by sales."""
    if not vehicle_model:
        return None
    brand = VehicleBrand.objects.filter(name__iexact=vehicle_model.brand).select_related(
        "parent"
    ).first()
    root_name = (brand.parent.name if brand and brand.parent_id else vehicle_model.brand)
    normalized_root = root_name.strip().casefold()
    if normalized_root == "sym":
        return SalesSourceBrandPolicy.CooperationScope.SYM
    if normalized_root == "suzuki":
        if vehicle_model.energy_type == VehicleModel.EnergyType.GAS:
            return SalesSourceBrandPolicy.CooperationScope.SUZUKI_GAS
        return SalesSourceBrandPolicy.CooperationScope.SUZUKI_ELECTRIC
    return None


def resolve_dealer_brand_policy(source_id, vehicle_model, effective_date):
    scope = cooperation_scope_for_vehicle_model(vehicle_model)
    if not source_id or not scope or not effective_date:
        return None
    return (
        SalesSourceBrandPolicy.objects.filter(
            source_id=source_id,
            source__source_type=SalesSource.SourceType.DEALER,
            cooperation_scope=scope,
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


def original_dealer_commission(order):
    """沿用原銷售車行的傭金金額，不因歸屬車行而改套費率。"""
    profile = OrderOperationsProfile.objects.filter(order=order).first()
    if profile and "dealer_commission_expense" in profile.manual_financial_fields:
        # 人工覆寫的是總支出，不能猜測其中的原傭金／獎金拆分。
        return None
    if order.source_type == SalesOrder.SourceType.STORE:
        # 本店指定台數不產生新的機種基礎傭金；保留既有明確的傭金拆分。
        return (profile.dealer_commission_base + profile.dealer_commission_adjustment) if profile else Decimal("0")
    if profile and profile.dealer_commission_locked_at:
        return profile.dealer_commission_base + profile.dealer_commission_adjustment
    policy = resolve_dealer_brand_policy(
        order.source_id, order.vehicle_model, order.registration_date or order.order_date,
    )
    return (order.vehicle_model.base_dealer_commission or Decimal("0")) + (
        policy.commission_adjustment if policy else Decimal("0")
    )


def _apply_bonus_expense(order):
    profile = OrderOperationsProfile.objects.filter(order=order).first()
    if not profile or (not profile.dealer_commission_locked_at and order.source_type != SalesOrder.SourceType.STORE):
        return apply_order_dealer_commission(order)
    if "dealer_commission_expense" not in profile.manual_financial_fields:
        profile.dealer_commission_expense = (
            profile.dealer_commission_base + profile.dealer_commission_adjustment
            + dealer_volume_bonus_total(order)
        )
        profile.save(update_fields=["dealer_commission_expense", "updated_at"])
    return profile


def apply_order_dealer_commission(order, *, lock=False):
    profile, _ = OrderOperationsProfile.objects.get_or_create(order=order)
    if profile.dealer_commission_locked_at:
        return _apply_bonus_expense(order)
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
        order.source_id, order.vehicle_model, effective_date
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


def matching_bonus_rules(order, dealer_id):
    """共用試算與期間鎖的條件；Exists 避免多選車型重複列及 PG DISTINCT 列鎖限制。"""
    if not dealer_id or not order.registration_date or not order.vehicle_model_id:
        return DealerVolumeBonusRule.objects.none()
    links = DealerVolumeBonusRule.vehicle_models.through.objects.filter(dealervolumebonusrule_id=OuterRef("pk"))
    return (DealerVolumeBonusRule.objects.filter(
        starts_on__lte=order.registration_date, ends_on__gte=order.registration_date,
    ).filter(Q(dealer_id=dealer_id) | Q(dealer__isnull=True))
        .filter(Q(brand="") | Q(brand__iexact=order.vehicle_model.brand))
        .filter(Q(energy_type="") | Q(energy_type=order.vehicle_model.energy_type))
        .annotate(has_models=Exists(links), matches_model=Exists(links.filter(vehiclemodel_id=order.vehicle_model_id)))
        .filter(Q(has_models=False) | Q(matches_model=True)))


def eligible_volume_bonus_orders(rule, dealer=None):
    # 收款對象必須是合作車行；本店單僅在明確指定車行後列入。
    dealer = dealer or rule.dealer
    if dealer and (dealer.source_type != SalesSource.SourceType.DEALER or (rule.dealer_id and dealer.pk != rule.dealer_id)):
        return SalesOrder.objects.none()
    orders = (SalesOrder.objects.filter(
        registration_date__range=(rule.starts_on, rule.ends_on), registration_completed_at__isnull=False,
    ).filter(
        Q(source_type=SalesOrder.SourceType.DEALER, source__source_type=SalesSource.SourceType.DEALER)
        | Q(source_type=SalesOrder.SourceType.STORE, commission_recipient__source_type=SalesSource.SourceType.DEALER)
    ).exclude(status=SalesOrder.Status.CANCELLED)
        .select_related("vehicle_model", "source", "commission_recipient").order_by("registration_date", "number"))
    if dealer:
        orders = orders.filter(Q(commission_recipient=dealer) | Q(commission_recipient__isnull=True, source=dealer))
    if rule.brand:
        orders = orders.filter(vehicle_model__brand__iexact=rule.brand)
    if rule.energy_type:
        orders = orders.filter(vehicle_model__energy_type=rule.energy_type)
    models = list(rule.vehicle_models.all()) if rule.pk else []
    if models:
        orders = orders.filter(vehicle_model_id__in=[model.pk for model in models])
    return orders


def bonus_rule_dealers(rule):
    if rule.dealer_id:
        return [rule.dealer] if rule.dealer.source_type == SalesSource.SourceType.DEALER else []
    ids = {order.effective_commission_recipient.pk for order in eligible_volume_bonus_orders(rule)}
    ids.update(rule.settlements.values_list("dealer_id", flat=True))
    return list(SalesSource.objects.filter(pk__in=ids, source_type=SalesSource.SourceType.DEALER).order_by("name"))


def preview_volume_bonus(rule, dealer=None, *, include_combined=False):
    dealer = dealer or rule.dealer
    if not dealer:
        raise ValueError("請先選擇收款車行，各車行須分開試算。")
    settlement = DealerVolumeBonusSettlement.objects.filter(rule=rule, dealer=dealer).first()
    if settlement:
        allocations = list(settlement.allocations.select_related("order__source", "order__vehicle_model"))
        orders = [item.order for item in allocations]
        original_amounts = {item.order_id: item.original_commission_amount for item in allocations}
    else:
        orders = list(eligible_volume_bonus_orders(rule, dealer))
        original_amounts = {o.pk: original_dealer_commission(o) for o in orders}
    preview = _build_volume_bonus_preview(rule, orders, original_amounts, settlement)
    preview.update(dealer=dealer, settlement=settlement)
    if include_combined:
        add_combined_bonus_details(preview, rule, dealer)
    return preview


def add_combined_bonus_details(preview, rule, dealer):
    """逐單呈現全部規則，不重複加原傭金；未結算與已入帳清楚區分。"""
    order_ids = {order.pk for order in preview["orders"]}
    details = {pk: [] for pk in order_ids}
    candidates = DealerVolumeBonusRule.objects.filter(
        Q(dealer=dealer) | Q(dealer__isnull=True),
        starts_on__lte=rule.ends_on, ends_on__gte=rule.starts_on,
    ).prefetch_related("vehicle_models", "tiers").order_by("pk")
    for candidate in candidates:
        settled = DealerVolumeBonusSettlement.objects.filter(rule=candidate, dealer=dealer).first()
        if settled:
            amounts = settled.allocations.filter(order_id__in=order_ids).values_list("order_id", "amount")
        elif candidate.active:
            other = preview_volume_bonus(candidate, dealer)
            amounts = [(order.pk, other["bonus_per_vehicle"]) for order in other["orders"] if order.pk in order_ids and other["tier"]]
        else:
            continue
        for pk, amount in amounts:
            details[pk].append({"name": str(candidate), "amount": amount, "settled": bool(settled), "current": candidate.pk == rule.pk})
    for order in preview["orders"]:
        order.bonus_details = details[order.pk]
        order.combined_bonus = sum((item["amount"] for item in order.bonus_details), Decimal("0"))
    preview["combined_bonus_total"] = sum((order.combined_bonus for order in preview["orders"]), Decimal("0"))


def _build_volume_bonus_preview(rule, orders, original_amounts, settlement=None):
    for order in orders:
        order.original_commission_amount = original_amounts[order.pk]
    original_total = (None if any(value is None for value in original_amounts.values())
                      else sum(original_amounts.values(), Decimal("0")))
    tier = rule.tiers.filter(minimum_quantity__lte=len(orders)).order_by(
        "-minimum_quantity"
    ).first()
    per_vehicle = settlement.bonus_per_vehicle if settlement else (tier.bonus_per_vehicle if tier else Decimal("0"))
    return {
        "orders": orders,
        "quantity": len(orders),
        "tier": tier,
        "bonus_per_vehicle": per_vehicle,
        "expected_amount": settlement.expected_amount if settlement else per_vehicle * len(orders),
        "original_commission_total": original_total,
        "total_payable": None if original_total is None else original_total + (
            settlement.actual_amount if settlement else per_vehicle * len(orders)
        ),
    }


def _allocation_amounts(total, count):
    total = Decimal(total)
    if not total.is_finite() or total < 0 or total != total.to_integral_value():
        raise ValueError("獎金金額必須為非負整數。")
    if not count:
        return []
    integer_total = int(total)
    base, remainder = divmod(integer_total, count)
    return [Decimal(base + (1 if index < remainder else 0)) for index in range(count)]


@transaction.atomic
def create_volume_bonus_settlement(rule, actor_name, actual_amount=None, reason="", *, dealer=None):
    rule = DealerVolumeBonusRule.objects.select_for_update().get(pk=rule.pk)
    dealer = dealer or rule.dealer
    if not dealer or dealer.source_type != SalesSource.SourceType.DEALER or (rule.dealer_id and dealer.pk != rule.dealer_id):
        raise ValueError("請選擇此規則適用的收款車行。")
    if DealerVolumeBonusSettlement.objects.filter(rule=rule, dealer=dealer).exists():
        raise ValueError("此規則已完成結算，不可重複建立。")
    if not rule.active:
        raise ValueError("已停用的規則不可結算。")
    # 只結算這次實際鎖定的訂單，不再查一次而混入未鎖定的新單。
    # 訂單變更歸屬使用相同列鎖；固定鎖定順序避免相互等待。
    orders = list(eligible_volume_bonus_orders(rule, dealer).select_for_update(of=("self",)).order_by("pk"))
    orders.sort(key=lambda order: (order.registration_date, order.number))
    preview = _build_volume_bonus_preview(
        rule, orders, {order.pk: original_dealer_commission(order) for order in orders},
    )
    if not preview["tier"]:
        raise ValueError("目前符合台數尚未達到任何獎金門檻。")
    # 不同規則允許同一訂單累加；同一規則與車行由列鎖及 unique constraint 保護。
    expected = preview["expected_amount"]
    actual = expected if actual_amount is None else Decimal(actual_amount)
    amounts = _allocation_amounts(actual, len(preview["orders"]))
    settlement = DealerVolumeBonusSettlement.objects.create(
        rule=rule,
        dealer=dealer,
        qualified_quantity=preview["quantity"],
        bonus_per_vehicle=preview["bonus_per_vehicle"],
        expected_amount=expected,
        actual_amount=actual,
        adjustment_reason=reason,
        settled_by=actor_name,
    )
    DealerVolumeBonusAllocation.objects.bulk_create(
        [
            DealerVolumeBonusAllocation(
                settlement=settlement,
                order=order,
                amount=amount,
                original_commission_amount=order.original_commission_amount,
            )
            for order, amount in zip(preview["orders"], amounts)
        ]
    )
    for order in preview["orders"]:
        _apply_bonus_expense(order)
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
    # 與其他規則結算／更正共用訂單列鎖，避免同單加總遺失。
    list(SalesOrder.objects.select_for_update().filter(pk__in=[item.order_id for item in allocations]).order_by("pk"))
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
        _apply_bonus_expense(allocation.order)
    return settlement
