"""車行獎勵活動（T-149）：依實際領牌日，把符合的活動項目存成訂單的車行獎勵明細。

- 只給有收款車行的訂單（車行單，或指定給車行的本店單）；本店單未指定車行與網路平台單沒有。
- 符合的活動全部累加；同一品項出現在兩個活動，各自一列（給付時可依活動追溯）。
- 尚未完成領牌：填了領牌日就帶入，活動或訂單改了會重算；完成領牌後固定。
- 完成領牌後改領牌日（T-147）由 `registration_edit` 以 force 重新套用；已完成領牌的舊單不會自動補。
- 明細只記錄承諾內容，不出庫、不入帳、不影響淨利；給付列表（T-150）直接讀 `OrderDealerRewardLine`。
"""
from collections import OrderedDict

from django.db import transaction

from sales.models import DealerRewardCampaign, OrderDealerRewardLine
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
def apply_order_dealer_rewards(order, *, force=False):
    """重新產生訂單的車行獎勵明細；完成領牌後只有 force（完成當下、改領牌日）才會重算。"""
    if order.registration_completed_at and not force:
        return []
    if order.status == order.Status.CANCELLED:
        return list(order.dealer_reward_lines.all())
    dealer = order_reward_dealer(order)
    vehicle_model = order.vehicle_model if order.vehicle_model_id else None
    campaigns = resolve_dealer_reward_campaigns(vehicle_model, dealer.pk if dealer else None, order.registration_date)
    OrderDealerRewardLine.objects.filter(order=order).delete()
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
            registration_date=order.registration_date,
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
    return {
        "dealer": dealer,
        "lines": lines,
        "totals": reward_totals(lines),
        "locked": bool(order.registration_completed_at),
        "registration_date": lines[0].registration_date if lines else order.registration_date,
    }
