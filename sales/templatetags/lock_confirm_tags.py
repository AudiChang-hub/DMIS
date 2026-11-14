"""領牌「確認完成」確認卡要列的值（使用者 2026-11-14 T-172 A′、T-176）：一律取資料庫現值，畫面看到的就是確認後會鎖定的值。"""
from django import template
from django.core.exceptions import ObjectDoesNotExist

from sales.models import RegistrationDocument
from sales.services.settlement_cost import resolve_settlement_cost

register = template.Library()


def _money(value):
    return f"{value or 0:,.0f}"


def plate_fee_text(order):
    """牌險規費：稅金總額＋強制險費用（使用者 11/13 簡報 p2：例 715+658=1373），與收支頁「領牌試算」同一組欄位。
    固定整包規則沒有分項、強制險含在整包裡，只列試算合計。"""
    total = order.registration_calculated_total or 0
    if order.registration_bundle_fee or order.registration_tax_total < 0 or not total:
        return f"{_money(total)} 元（試算合計）"
    return f"{_money(order.registration_tax_total)}＋{_money(order.compulsory_insurance_fee)}＝{_money(total)} 元（稅金＋強制險）"


def _campaign_change_text(before, after, *, paid=frozenset()):
    """before／after：{活動 id: 名稱}。列出保留、將撤銷、新符合；已給付的撤銷項目註明待追回。"""
    kept = [name for campaign_id, name in after.items() if campaign_id in before]
    added = [name for campaign_id, name in after.items() if campaign_id not in before]
    revoked = [
        f"{name}（已給付，將列待追回）" if campaign_id in paid else name
        for campaign_id, name in before.items() if campaign_id not in after
    ]
    parts = []
    if kept:
        parts.append("保留 " + "、".join(kept))
    if revoked:
        parts.append("⚠ 將撤銷 " + "、".join(revoked))
    if added:
        parts.append("新符合 " + "、".join(added))
    return "；".join(parts) or "沒有符合的活動"


def _incentive_row(order, profile):
    from sales.services.dealer_reward_campaign import order_reward_dealer
    from sales.services.incentive_rule import INCENTIVE_FIELDS, resolve_incentive_campaigns

    before = {} if profile is None else {
        application.campaign_id: application.campaign_name for application in profile.incentive_applications.all()
    }
    dealer = order_reward_dealer(order)
    resolved = resolve_incentive_campaigns(
        order.vehicle_model if order.vehicle_model_id else None, order.source_type, order.registration_date,
        dealer.pk if dealer else None,
    )
    after = {campaign.pk: campaign.name for campaign, _amounts, _given in resolved}
    if not before and not after:
        return None
    text = _campaign_change_text(before, after)
    manual = set(profile.manual_financial_fields or []) & set(INCENTIVE_FIELDS) if profile else set()
    if manual and set(before) - set(after):
        text += "；人工輸入的金額不會自動改"
    return ("原廠獎勵", text)


def _dealer_reward_row(order):
    from sales.reporting.payout_models import DealerPayoutEntry
    from sales.services.dealer_reward_campaign import order_reward_dealer, resolve_dealer_reward_campaigns

    dealer = order_reward_dealer(order)
    before = dict(order.dealer_reward_lines.values_list("campaign_id", "campaign_name"))
    after = {
        campaign.pk: campaign.name
        for campaign in resolve_dealer_reward_campaigns(
            order.vehicle_model if order.vehicle_model_id else None, dealer.pk if dealer else None, order.registration_date,
        )
    }
    if not before and not after:
        return None
    prefix = f"reward:order:{order.pk}:campaign:"
    paid = {
        int(key[len(prefix):].split(":", 1)[0])
        for key in DealerPayoutEntry.objects.filter(source_key__startswith=prefix, paid=True).values_list("source_key", flat=True)
    }
    return ("車行獎勵", _campaign_change_text(before, after, paid=paid))


@register.simple_tag
def registration_lock_rows(order):
    """確認領牌完成前列出：實際領牌日、車牌、牌險規費明細、車輛結算成本、原廠與車行獎勵的變化、已上傳的領牌文件。
    獎勵依這個日期重新判斷（T-176）：確認前依訂單成立日預先觸發的活動，不符合的會撤銷。文件全部選填，只列份數。"""
    rows = [
        ("實際領牌日期", f"{order.registration_date:%Y/%m/%d}" if order.registration_date else "", not order.registration_date),
        ("車牌號碼", order.final_plate_number or "", not order.final_plate_number),
        ("牌險規費", plate_fee_text(order), False),
    ]
    try:
        profile = order.operations
    except ObjectDoesNotExist:
        profile = None
    rule = resolve_settlement_cost(order.vehicle_model_id, order.registration_date)
    if profile is not None and profile.vehicle_cost_manual:
        cost, missing = f"{_money(profile.vehicle_cost)} 元（人工輸入）", False
    elif rule:
        cost, missing = f"{_money(rule.amount)} 元", False
    else:
        cost, missing = "找不到成本規則，請先補建", bool(order.registration_date)
    rows.append(("車輛結算成本", cost, missing))
    if order.registration_date:
        for row in (_incentive_row(order, profile), _dealer_reward_row(order)):
            if row:
                rows.append((*row, False))
    uploaded = order.registration_documents.exclude(
        document_type__in=RegistrationDocument.retired_document_types()
    ).count()
    rows.append(("領牌文件", f"已上傳 {uploaded} 份（選填）", False))
    return [{"label": label, "value": value, "missing": missing} for label, value, missing in rows]
