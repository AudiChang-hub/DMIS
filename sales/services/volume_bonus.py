"""台數獎金自動計算（T-148，使用者 2026-11-11 選 B＋Y）。

- 不再手動「確認結算」：依規則（期間、條件、門檻、適用車行）自動算出每張單的台數獎金。
- 每條規則、每個統計期間、每家收款車行各自算台數；達到的最高門檻，群組內每張單都拿該門檻的每台金額。
  不同規則累加。適用車行可複選（每家各自計算），未選＝全部車行逐家計算。
- 期間內是預估（`posted_at` 空白），只在報表與台數試算顯示，不進傭金支出；
  期間結束後自動入帳（每日排程 `sync_volume_bonus`，或下一次重算時補上），之後異動仍自動重算。
- 入帳的獎金加進傭金支出；人工改過傭金支出、Excel 匯入單不覆蓋（只列在報表與試算）。
- 台數獎金是另外付給車行的錢，不扣本單應收（見 customer_receivable.dealer_cash_credit）。
"""
import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from sales.models import (
    DealerVolumeBonusPeriod,
    DealerVolumeBonusRule,
    OrderEvent,
    OrderOperationsProfile,
    OrderVolumeBonus,
    SalesOrder,
    SalesSource,
)
from sales.services.audit_note import money
from sales.services.dealer_commission import (
    _apply_bonus_expense,
    eligible_volume_bonus_orders,
    matching_bonus_rules,
    rule_dealer_ids,
)

logger = logging.getLogger(__name__)
ZERO = Decimal("0")
ACTOR = "系統（台數獎金自動計算）"


def is_posted_period(period, today=None):
    return period.ends_on < (today or timezone.localdate())


def scope_dealers(rule, period):
    """需要計算的收款車行：已有獎金列的車行，加上目前可能達標的車行。"""
    ids = set(OrderVolumeBonus.objects.filter(rule=rule, period=period).values_list("dealer_id", flat=True))
    if rule.active:
        linked = rule_dealer_ids(rule)
        if linked:
            ids.update(linked)
        else:
            ids.update(order.effective_commission_recipient.pk
                       for order in eligible_volume_bonus_orders(rule, period=period))
    return list(SalesSource.objects.filter(pk__in=ids).order_by("pk"))


def group_preview(rule, period, dealer):
    """唯讀試算：本群組符合的訂單、台數、達到的門檻與下一級。"""
    orders = list(eligible_volume_bonus_orders(rule, dealer, period=period)) if rule.active else []
    tiers = list(rule.tiers.all())
    reached = [tier for tier in tiers if tier.minimum_quantity <= len(orders)]
    tier = max(reached, key=lambda item: item.minimum_quantity) if reached else None
    upcoming = [tier for tier in tiers if tier.minimum_quantity > len(orders)]
    next_tier = min(upcoming, key=lambda item: item.minimum_quantity) if upcoming else None
    per_vehicle = tier.bonus_per_vehicle if tier else ZERO
    rows = {row.order_id: row for row in OrderVolumeBonus.objects.filter(rule=rule, period=period, dealer=dealer)}
    for order in orders:
        order.volume_bonus_row = rows.get(order.pk)
        order.volume_bonus_note = commission_note(order)
    return {
        "dealer": dealer,
        "orders": orders,
        "quantity": len(orders),
        "tier": tier,
        "next_tier": next_tier,
        "shortfall": next_tier.minimum_quantity - len(orders) if next_tier else 0,
        "bonus_per_vehicle": per_vehicle,
        "total": per_vehicle * len(orders),
        "posted": is_posted_period(period),
    }


def commission_note(order):
    """入帳後不會自動加進傭金支出的原因；空字串＝會加入。"""
    if hasattr(order, "legacy_snapshot"):
        return "匯入單：傭金以 Excel 為準"
    profile = OrderOperationsProfile.objects.filter(order=order).only("manual_financial_fields").first()
    if profile and "dealer_commission_expense" in (profile.manual_financial_fields or []):
        return "人工傭金：不自動加入"
    return ""


def _recompute_scope(rule, period, dealer, now, changes):
    posted = is_posted_period(period, timezone.localdate(now))
    orders = list(eligible_volume_bonus_orders(rule, dealer, period=period)) if rule.active else []
    tier = (rule.tiers.filter(minimum_quantity__lte=len(orders)).order_by("-minimum_quantity").first()
            if orders else None)
    order_ids = [order.pk for order in orders]
    in_scope = {row.order_id: row for row in OrderVolumeBonus.objects.filter(rule=rule, period=period, dealer=dealer)}
    keep = set()
    if tier and tier.bonus_per_vehicle > 0:
        # 換了收款車行的單：同一規則、期間的列直接移過來（唯一鍵是規則＋期間＋訂單）。
        moved = {row.order_id: row for row in OrderVolumeBonus.objects.filter(
            rule=rule, period=period, order_id__in=order_ids).exclude(dealer=dealer)}
        for order in orders:
            row = in_scope.get(order.pk) or moved.get(order.pk)
            before = row.amount if row and row.posted_at else ZERO
            values = {
                "dealer": dealer, "quantity": len(orders), "minimum_quantity": tier.minimum_quantity,
                "amount": tier.bonus_per_vehicle,
                "posted_at": ((row.posted_at if row and row.posted_at else now) if posted else None),
            }
            if row is None:
                row = OrderVolumeBonus.objects.create(order=order, rule=rule, period=period, **values)
            elif any(getattr(row, name) != value for name, value in values.items()):
                for name, value in values.items():
                    setattr(row, name, value)
                row.save(update_fields=[*values, "updated_at"])
            keep.add(order.pk)
            after = row.amount if row.posted_at else ZERO
            if after != before:
                changes.setdefault(order.pk, []).append(
                    f"{rule}／{period.label}：{money(before)} → {money(after)}（{len(orders)} 台，達 {tier.minimum_quantity} 台門檻）")
    for order_id, row in in_scope.items():
        if order_id in keep:
            continue
        if row.posted_at and row.amount:
            changes.setdefault(order_id, []).append(f"{rule}／{period.label}：{money(row.amount)} → 0（不再符合或未達門檻）")
        row.delete()


def _apply_changes(changes):
    for order_id, lines in changes.items():
        order = SalesOrder.all_objects.filter(pk=order_id).first()
        if not order:
            continue
        refresh_order_commission(order)
        OrderEvent.objects.create(order=order, event_type="volume_bonus_adjusted", actor_name=ACTOR,
                                  description="台數獎金自動調整：" + "；".join(lines))


def refresh_order_commission(order):
    """把已入帳的台數獎金反映到傭金支出；匯入單與人工傭金不動。"""
    if hasattr(order, "legacy_snapshot"):
        return None
    return _apply_bonus_expense(order)


def _lock_rules(rule_ids):
    return list(DealerVolumeBonusRule.objects.select_for_update().filter(pk__in=rule_ids)
                .prefetch_related("tiers", "dealer_links", "brands", "vehicle_models").order_by("pk"))


@transaction.atomic
def recompute_rule(rule_id, *, now=None):
    now = now or timezone.now()
    rules = _lock_rules([rule_id])
    changes = {}
    for rule in rules:
        for period in rule.periods.all():
            for dealer in scope_dealers(rule, period):
                _recompute_scope(rule, period, dealer, now, changes)
    _apply_changes(changes)
    return changes


@transaction.atomic
def recompute_for_order(order_id, *, now=None):
    """訂單異動後：重算這張單原本所在、以及現在符合的群組（同群組其他單一起更新）。"""
    now = now or timezone.now()
    scopes = set(OrderVolumeBonus.objects.filter(order_id=order_id).values_list("rule_id", "period_id", "dealer_id"))
    order = SalesOrder.objects.filter(pk=order_id).select_related("vehicle_model").first()
    dealer_id = (order.commission_recipient_id or order.source_id) if order else None
    if order and dealer_id and order.registration_date and order.registration_completed_at:
        for rule_id in matching_bonus_rules(order, dealer_id).filter(active=True).values_list("pk", flat=True):
            for period_id in DealerVolumeBonusPeriod.objects.filter(
                    rule_id=rule_id, starts_on__lte=order.registration_date,
                    ends_on__gte=order.registration_date).values_list("pk", flat=True):
                scopes.add((rule_id, period_id, dealer_id))
    if not scopes:
        return {}
    rules = {rule.pk: rule for rule in _lock_rules({scope[0] for scope in scopes})}
    periods = DealerVolumeBonusPeriod.objects.in_bulk({scope[1] for scope in scopes})
    dealers = SalesSource.objects.in_bulk({scope[2] for scope in scopes})
    changes = {}
    for rule_id, period_id, scope_dealer_id in sorted(scopes):
        if rule_id in rules and period_id in periods and scope_dealer_id in dealers:
            _recompute_scope(rules[rule_id], periods[period_id], dealers[scope_dealer_id], now, changes)
    _apply_changes(changes)
    return changes


def sync_all(*, now=None):
    """全部規則重算一次（每日排程）：期間結束的自動入帳，也補上漏掉的觸發。冪等。"""
    changed = 0
    for rule_id in DealerVolumeBonusRule.objects.order_by("pk").values_list("pk", flat=True):
        changed += len(recompute_rule(rule_id, now=now))
    return changed


def _run_safely(function, pk):
    try:
        function(pk)
    except Exception:  # 已提交的業務資料不能因獎金重算失敗而回 500；每日排程會再補算。
        logger.exception("台數獎金自動重算失敗：%s(%s)", function.__name__, pk)


def schedule_order_refresh(order_id):
    transaction.on_commit(lambda: _run_safely(recompute_for_order, order_id))


def schedule_rule_refresh(rule_id):
    transaction.on_commit(lambda: _run_safely(recompute_rule, rule_id))


def schedule_commission_refresh(order_ids):
    def run():
        for order in SalesOrder.all_objects.filter(pk__in=list(order_ids)):
            try:
                refresh_order_commission(order)
                OrderEvent.objects.create(order=order, event_type="volume_bonus_adjusted", actor_name=ACTOR,
                                          description="台數獎金規則或期間已刪除，已入帳的獎金從傭金支出移除")
            except Exception:
                logger.exception("台數獎金刪除後更新傭金失敗：訂單 %s", order.pk)
    if order_ids:
        transaction.on_commit(run)
