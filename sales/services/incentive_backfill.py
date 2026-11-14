"""原廠獎勵活動回溯（T-161，使用者 2026-11-13）：掃描既有訂單，由使用者逐張勾選後覆寫收支。

- 掃描只讀（GET）：依領牌日落在活動期間、通路、收款車行、車型條件找訂單；只列系統建立的單
  （Excel 匯入單完全不列）與未取消的單。每張單列出目前金額、套用後金額（依目前全部活動重算），
  並標出「已領牌固定」「人工改過」。
- 覆寫（POST）：同一交易內鎖定訂單收支，核對預覽後金額沒有被改動（被改就整批不寫入），
  只寫三個獎勵欄位與活動明細；人工改過的欄位改回系統值；已固定的單維持固定。每張單留 OrderChange。
  其他收支（強制險傭金、實際車價收入、成本、傭金）一律不動。
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from sales.models import OrderChange, OrderOperationsProfile, SalesOrder, registration_confirmed_q
from sales.services.campaign_conditions import matching_models
from sales.services.dealer_reward_campaign import order_reward_dealer
from sales.services.incentive_rule import INCENTIVE_FIELDS, incentive_totals, replace_incentive_applications

FIELD_LABELS = {
    "sales_bonus": "實銷獎勵金",
    "promotion_subsidy": "促銷補助金",
    "installment_interest_subsidy": "分期補貼息",
}


def _amounts(profile):
    return {field: Decimal(getattr(profile, field) or 0) if profile else Decimal("0") for field in INCENTIVE_FIELDS}


def candidate_orders(campaign):
    """判斷日在期間內、車型符合、系統建立且未取消的訂單（不含 Excel 匯入單）。

    判斷日＝已確認領牌的單用實際領牌日，尚未確認的單用訂單成立日（T-176；預計領牌日不算）。
    """
    model_ids = set(matching_models(
        campaign.brands, campaign.energy_types, list(campaign.vehicle_models.values_list("pk", flat=True)),
    ).values_list("pk", flat=True))
    end = campaign.effective_to or timezone.localdate()
    if campaign.is_paused or not model_ids or end < campaign.effective_from:
        return SalesOrder.objects.none()
    return (
        SalesOrder.objects.filter(
            (registration_confirmed_q() & Q(registration_date__gte=campaign.effective_from, registration_date__lte=end))
            | (Q(registration_completed_at__isnull=True)
               & Q(established_on__gte=campaign.effective_from, established_on__lte=end)),
            vehicle_model_id__in=model_ids, legacy_snapshot__isnull=True,
            source_type__in=campaign.source_types,
        )
        .exclude(status=SalesOrder.Status.CANCELLED)
        .select_related("vehicle_model", "source", "commission_recipient", "operations")
        .order_by("registration_date", "established_on", "pk")
    )


def scan(campaign):
    rows = []
    for order in candidate_orders(campaign):
        dealer = order_reward_dealer(order)
        if not campaign.applies_to_dealer(dealer.pk if dealer else None):
            continue
        profile = getattr(order, "operations", None)
        current = _amounts(profile)
        _rows, after, _matched, _promo, _regular = incentive_totals(
            order.vehicle_model, order.source_type, order.reward_basis_date, dealer.pk if dealer else None,
        )
        manual = sorted(set(profile.manual_financial_fields or []) & set(INCENTIVE_FIELDS)) if profile else []
        locked = bool(profile and profile.incentive_locked_at)
        changed = current != after
        rows.append({
            "order": order,
            "current": current,
            "after": after,
            "changed": changed,
            "locked": locked,
            "manual": [FIELD_LABELS[field] for field in manual],
            "default_checked": changed and not locked and not manual,
            "token": "|".join(str(int(current[field])) for field in INCENTIVE_FIELDS),
        })
    return rows


@transaction.atomic
def apply(campaign, selections, actor_name):
    """selections：{訂單 id: 預覽時的 token}。回傳覆寫的訂單數；任何一張預覽後被改動就整批不寫入。"""
    in_scope = {row["order"].pk: row for row in scan(campaign)}
    unknown = [order_id for order_id in selections if order_id not in in_scope]
    if unknown:
        raise ValidationError("有訂單已不符合這個活動的條件，請重新掃描。")
    profiles = {
        profile.order_id: profile
        for profile in OrderOperationsProfile.objects.select_for_update(of=("self",)).filter(order_id__in=selections)
    }
    updated = 0
    for order_id, token in selections.items():
        row = in_scope[order_id]
        order = row["order"]
        profile = profiles.get(order_id) or OrderOperationsProfile.objects.create(order=order)
        before = _amounts(profile)
        if "|".join(str(int(before[field])) for field in INCENTIVE_FIELDS) != token:
            raise ValidationError(f"訂單 {order.pk} 的金額在掃描後被改過，未寫入任何訂單，請重新掃描。")
        dealer = order_reward_dealer(order)
        rows, totals, matched, _promo, regular = incentive_totals(
            order.vehicle_model, order.source_type, order.reward_basis_date, dealer.pk if dealer else None,
        )
        manual_before = list(profile.manual_financial_fields or [])
        for field in INCENTIVE_FIELDS:
            setattr(profile, field, totals[field])
        profile.manual_financial_fields = sorted(set(manual_before) - set(INCENTIVE_FIELDS))
        profile.incentive_rule = regular.legacy_rule if regular else None
        profile.incentive_registration_date = order.reward_basis_date if matched else None
        profile.save(update_fields=[
            *INCENTIVE_FIELDS, "manual_financial_fields", "incentive_rule", "incentive_registration_date", "updated_at",
        ])
        replace_incentive_applications(profile, rows, order.reward_basis_date)
        changes = {
            FIELD_LABELS[field]: {"before": str(int(before[field])), "after": str(int(totals[field]))}
            for field in INCENTIVE_FIELDS if before[field] != totals[field]
        }
        released = sorted(set(manual_before) & set(INCENTIVE_FIELDS))
        if released:
            changes["人工改過的欄位"] = {"before": "、".join(FIELD_LABELS[f] for f in released), "after": "改回系統帶入"}
        OrderChange.objects.create(
            order=order, actor_name=actor_name, changes=changes,
            reason=f"原廠獎勵活動回溯：{campaign.name}（依 {order.registration_date:%Y/%m/%d} 領牌重新套用）",
        )
        updated += 1
    return updated
