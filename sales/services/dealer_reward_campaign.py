"""車行獎勵活動（T-149）：把符合的活動項目存成訂單的車行獎勵明細。

- 只給有收款車行的訂單（車行單，或指定給車行的本店單）；本店單未指定車行與網路平台單沒有。
- 符合的活動全部累加；同一品項出現在兩個活動，各自一列（給付時可依活動追溯）。
- 判斷日（T-176，使用者 2026-11-14）：確認領牌前依訂單成立日預先觸發，填的預計領牌日不影響；
  按「確認完成」後依實際領牌日判斷，原本有、現在不符合的活動撤銷並寫 OrderEvent。
  已勾「已給付」的項目撤銷後列在給付列表「資格撤銷・待追回」，由使用者按已追回或不追回結案。
- 尚未確認領牌：活動或訂單改了會重算；確認後固定。明細的「認列領牌日」存當時的判斷日。
- 確認後改領牌日（T-147）由 `registration_edit` 以 force 重新套用；已完成領牌的舊單不會自動補。
- 明細只記錄承諾內容，不出庫、不入帳、不影響淨利；給付列表（T-150）直接讀 `OrderDealerRewardLine`。
"""
from collections import OrderedDict

from django.db import transaction

from sales.models import DealerRewardCampaign, OrderDealerRewardLine, OrderEvent
from sales.services.campaign_conditions import active_on, vehicle_matches


def resolve_dealer_reward_campaigns(vehicle_model, dealer_id, registration_date):
    if vehicle_model is None or not dealer_id or not registration_date:
        return []
    candidates = active_on(
        DealerRewardCampaign.objects.prefetch_related("vehicle_models", "dealers", "items"), registration_date,
    ).order_by("pk")
    matched = []
    for campaign in candidates:
        dealer_ids = {dealer.pk for dealer in campaign.dealers.all()}
        if dealer_ids and dealer_id not in dealer_ids:
            continue
        if vehicle_matches(campaign, vehicle_model):
            matched.append(campaign)
    return matched


def order_reward_dealer(order):
    recipient = order.effective_commission_recipient
    return recipient if recipient is not None and recipient.source_type == recipient.SourceType.DEALER else None


@transaction.atomic
def apply_order_dealer_rewards(order, *, force=False, actor_name=""):
    """重新產生訂單的車行獎勵明細；完成領牌後只有 force（完成當下、改領牌日）才會重算。"""
    if order.registration_completed_at and not force:
        return []
    if order.status == order.Status.CANCELLED:
        return list(order.dealer_reward_lines.all())
    dealer = order_reward_dealer(order)
    vehicle_model = order.vehicle_model if order.vehicle_model_id else None
    basis_date = order.reward_basis_date
    campaigns = resolve_dealer_reward_campaigns(vehicle_model, dealer.pk if dealer else None, basis_date)
    previous = dict(OrderDealerRewardLine.objects.filter(order=order).values_list("campaign_id", "campaign_name"))
    OrderDealerRewardLine.objects.filter(order=order).delete()
    kept = {campaign.pk for campaign in campaigns}
    revoked = [name for campaign_id, name in previous.items() if campaign_id not in kept]
    if revoked:
        from sales.services.incentive_rule import basis_label

        OrderEvent.objects.create(
            order=order,
            event_type="dealer_reward_revoked",
            description=f"車行獎勵活動資格撤銷：{'、'.join(revoked)}（依{basis_label(order)} {basis_date:%Y/%m/%d} "
                        "不符合活動條件或期間；已給付的項目列在車行給付列表「資格撤銷・待追回」）",
            actor_name=actor_name or "系統",
        )
    lines = [
        OrderDealerRewardLine(
            order=order,
            campaign=campaign,
            campaign_name=campaign.name,
            dealer=dealer,
            catalog_item_id=item.catalog_item_id,
            reward_type=item.reward_type,
            name=item.name,
            quantity=item.quantity,
            unit=item.unit,
            unit_cost_snapshot=item.unit_cost_snapshot,
            cost_effective_on_snapshot=item.cost_effective_on_snapshot,
            note=item.note,
            registration_date=basis_date,
        )
        for campaign in campaigns
        for item in campaign.items.all()
    ]
    return OrderDealerRewardLine.objects.bulk_create(lines)


def reward_totals(lines):
    """同一品項（名稱＋單位）的數量合計，供訂單頁摘要；明細仍逐活動列出。"""
    totals = OrderedDict()
    for line in lines:
        key = (line.name, line.unit)
        totals[key] = totals.get(key, 0) + line.quantity
    return [
        {"name": name, "unit": unit, "quantity": format(quantity.normalize(), "f")}
        for (name, unit), quantity in totals.items()
    ]


def order_dealer_rewards(order):
    """訂單頁唯讀區塊：收款車行、明細、合計與狀態。"""
    lines = list(order.dealer_reward_lines.select_related("dealer").order_by("id"))
    dealer = lines[0].dealer if lines else order_reward_dealer(order)
    confirmed = bool(order.registration_completed_at)
    return {
        "dealer": dealer,
        "lines": lines,
        "totals": reward_totals(lines),
        "locked": confirmed,
        # 判斷日：確認領牌後是實際領牌日，確認前是訂單成立日（預先觸發，T-176）。
        "registration_date": lines[0].registration_date if lines else order.reward_basis_date,
        "basis_label": "實際領牌日" if confirmed else "訂單成立日",
        "pre_triggered": not confirmed,
    }
