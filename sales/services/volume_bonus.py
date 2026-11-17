"""台數獎金計算與結算（T-148 自動計算；T-203 改為月底手動結算）。

- 依規則（期間、條件、門檻、適用車行）自動算出每張單的台數獎金（T-148，使用者 2026-11-11 選 B＋Y）：
  每條規則、每個統計期間、每家收款車行各自算台數；達到的最高門檻，群組內每張單都拿該門檻的每台金額。
  不同規則累加。適用車行可複選（每家各自計算），未選＝全部車行逐家計算。
- 期間內和期間結束後都只是試算（`posted_at` 空白），不進傭金支出、淨利、車行結算卡、掛帳（T-203，使用者 2026-11-17 選 C，
  取代 T-148「期間結束自動入帳」）。每日排程 `sync_volume_bonus` 只更新試算。
- 月底在報表中心〈車行傭金／獎金給付〉按「結算」（規則×期間×車行一組，`settle_group`）：各單 `posted_at` 填結算時間、
  金額固定，加進傭金支出，淨利跟著反映；人工傭金與 Excel 匯入單不覆蓋傭金。另外發放給車行，不扣任何應收或掛帳。
- 結算後不自動重算（改領牌日、歸屬、刪單、退車都不改金額，也不自動收回），只標「結算後有變」（`settlement_changes`）；
  可「取消結算」（`cancel_settlement`）後重新結算。已勾「已給付」的要先取消給付才能取消結算。
"""
import logging
from decimal import Decimal

from django.core.exceptions import ValidationError
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
    VolumeBonusSettlement,
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


def period_ended(period, today=None):
    """統計期間已結束（隔天起）才能結算。"""
    return period.ends_on < (today or timezone.localdate())


def active_settlement(rule, period, dealer):
    return VolumeBonusSettlement.objects.filter(
        rule=rule, period=period, dealer=dealer, cancelled_at__isnull=True).first()


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
    """唯讀試算：本群組符合的訂單、台數、達到的門檻與下一級，以及結算狀態。"""
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
    ended = period_ended(period)
    # 期間還沒結束不可能已結算，不另查（營運總表的進度卡只看進行中的期間）。
    settlement = active_settlement(rule, period, dealer) if ended else None
    return {
        "dealer": dealer,
        "orders": orders,
        "quantity": len(orders),
        "tier": tier,
        "next_tier": next_tier,
        "shortfall": next_tier.minimum_quantity - len(orders) if next_tier else 0,
        "bonus_per_vehicle": per_vehicle,
        "total": per_vehicle * len(orders),
        "ended": ended,
        "settlement": settlement,
        "changes": settlement_changes(settlement) if settlement else [],
    }


def commission_note(order):
    """結算後不會自動加進傭金支出的原因；空字串＝會加入。"""
    if hasattr(order, "legacy_snapshot"):
        return "匯入單：傭金以 Excel 為準"
    profile = OrderOperationsProfile.objects.filter(order=order).only("manual_financial_fields").first()
    if profile and "dealer_commission_expense" in (profile.manual_financial_fields or []):
        return "人工傭金：不自動加入"
    return ""


def _settled_elsewhere(rule, period, dealer, order_ids):
    """同規則同期間、已在其他車行那組結算的單：獎金已固定在那一組，這一組不再計入。"""
    return set(OrderVolumeBonus.objects.filter(
        rule=rule, period=period, order_id__in=order_ids, posted_at__isnull=False,
    ).exclude(dealer=dealer).values_list("order_id", flat=True))


def _recompute_scope(rule, period, dealer, now, changes):
    """更新一組（規則×期間×車行）的試算列；已結算的組金額固定、不重算（T-203）。"""
    if active_settlement(rule, period, dealer):
        return
    orders = list(eligible_volume_bonus_orders(rule, dealer, period=period)) if rule.active else []
    if orders:
        settled = _settled_elsewhere(rule, period, dealer, [order.pk for order in orders])
        orders = [order for order in orders if order.pk not in settled]
    tier = (rule.tiers.filter(minimum_quantity__lte=len(orders)).order_by("-minimum_quantity").first()
            if orders else None)
    order_ids = [order.pk for order in orders]
    in_scope = {row.order_id: row for row in OrderVolumeBonus.objects.filter(rule=rule, period=period, dealer=dealer)}
    keep = set()
    if tier and tier.bonus_per_vehicle > 0:
        # 換了收款車行的單：同一規則、期間的試算列直接移過來（唯一鍵是規則＋期間＋訂單）；已結算的列不動。
        moved = {row.order_id: row for row in OrderVolumeBonus.objects.filter(
            rule=rule, period=period, order_id__in=order_ids, posted_at__isnull=True).exclude(dealer=dealer)}
        for order in orders:
            row = in_scope.get(order.pk) or moved.get(order.pk)
            before = row.amount if row and row.posted_at else ZERO
            values = {
                "dealer": dealer, "quantity": len(orders), "minimum_quantity": tier.minimum_quantity,
                "amount": tier.bonus_per_vehicle,
                # 未結算的組一律是試算；只有按「結算」才會填上結算時間（T-203）。
                "posted_at": None,
            }
            if row is None:
                row = OrderVolumeBonus.objects.create(order=order, rule=rule, period=period, **values)
            elif any(getattr(row, name) != value for name, value in values.items()):
                for name, value in values.items():
                    setattr(row, name, value)
                row.save(update_fields=[*values, "updated_at"])
            keep.add(order.pk)
            if before:
                changes.setdefault(order.pk, []).append(
                    f"{rule}／{period.label}：{money(before)} → 0（沒有有效結算，回到試算）")
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
    """把已結算的台數獎金反映到傭金支出；匯入單與人工傭金不動。"""
    if hasattr(order, "legacy_snapshot"):
        return None
    return _apply_bonus_expense(order)


def _lock_rules(rule_ids):
    return list(DealerVolumeBonusRule.objects.select_for_update(of=("self",)).filter(pk__in=rule_ids)
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
    """訂單異動後：重算這張單原本所在、以及現在符合的群組（同群組其他單一起更新；已結算的組不動）。"""
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
    """全部規則重算一次（每日排程）：只更新未結算組的試算，補上漏掉的觸發；不入帳（T-203）。冪等。"""
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
                                          description="台數獎金規則或期間已刪除，已結算的獎金從傭金支出移除")
            except Exception:
                logger.exception("台數獎金刪除後更新傭金失敗：訂單 %s", order.pk)
    if order_ids:
        transaction.on_commit(run)


# ── 結算（T-203，使用者 2026-11-17 選 C）─────────────────────────────────


def _group_rows(rule, period, dealer):
    return list(OrderVolumeBonus.objects.filter(rule=rule, period=period, dealer=dealer, amount__gt=0)
                .select_related("order").order_by("order__registration_date", "order_id"))


def settlement_changes(settlement):
    """結算後有變：比對結算固定的各單與目前的試算（台數、每台金額、進出的訂單）。空清單＝沒有變動。"""
    rule, period, dealer = settlement.rule, settlement.period, settlement.dealer
    settled = {row.order_id: row for row in OrderVolumeBonus.objects.filter(
        rule=rule, period=period, dealer=dealer, posted_at__isnull=False).select_related("order")}
    current = list(eligible_volume_bonus_orders(rule, dealer, period=period)) if rule.active else []
    tier = (rule.tiers.filter(minimum_quantity__lte=len(current)).order_by("-minimum_quantity").first()
            if current else None)
    per_vehicle = tier.bonus_per_vehicle if tier else ZERO
    lines = []
    if not rule.active:
        lines.append("規則已停用")
    if len(current) != settlement.quantity or per_vehicle != settlement.bonus_per_vehicle:
        lines.append(f"目前 {len(current)} 台、每台 {money(per_vehicle)}"
                     f"（結算時 {settlement.quantity} 台、每台 {money(settlement.bonus_per_vehicle)}）")
    current_ids = {order.pk for order in current}
    left = [row.order.number for order_id, row in settled.items() if order_id not in current_ids]
    joined = [order.number for order in current if order.pk not in settled]
    if left:
        lines.append("已不符合：" + "、".join(left))
    if joined:
        lines.append("新符合：" + "、".join(joined))
    return lines


def _settlement_event(order, description, actor_name):
    OrderEvent.objects.create(order=order, event_type="volume_bonus_settled", actor_name=actor_name,
                              description=description)


@transaction.atomic
def settle_group(rule_id, period_id, dealer_id, actor_name, *, expected_total=None, now=None):
    """結算一組（規則×期間×車行）：各單獎金固定、加進傭金支出，另外發放給車行（不扣應收或掛帳）。

    `expected_total` 是確認卡上顯示的合計；和目前試算不同時擋下，請使用者重新整理後再確認。
    """
    now = now or timezone.now()
    rules = _lock_rules([rule_id])
    if not rules:
        raise ValidationError("台數獎金規則已不存在，請重新整理。")
    rule = rules[0]
    period = DealerVolumeBonusPeriod.objects.filter(pk=period_id, rule=rule).first()
    dealer = SalesSource.objects.filter(pk=dealer_id).first()
    if period is None or dealer is None:
        raise ValidationError("統計期間或車行已不存在，請重新整理。")
    if not period_ended(period, timezone.localdate(now)):
        raise ValidationError(f"{period.label} 還沒結束，期間結束隔天起才能結算。")
    if active_settlement(rule, period, dealer):
        raise ValidationError("這一組已經結算過了，請重新整理。")
    _recompute_scope(rule, period, dealer, now, {})
    rows = _group_rows(rule, period, dealer)
    if not rows:
        raise ValidationError(f"{dealer.name} 在 {period.label} 沒有達到門檻，沒有台數獎金可以結算。")
    total = sum((row.amount for row in rows), ZERO)
    if expected_total is not None and Decimal(expected_total) != total:
        raise ValidationError(f"台數獎金已變動（目前 {money(total)}），請重新整理後再確認結算。")
    settlement = VolumeBonusSettlement.objects.create(
        rule=rule, period=period, dealer=dealer, quantity=len(rows),
        minimum_quantity=rows[0].minimum_quantity, bonus_per_vehicle=rows[0].amount, total_amount=total,
        settled_at=now, settled_by=actor_name,
    )
    OrderVolumeBonus.objects.filter(pk__in=[row.pk for row in rows]).update(posted_at=now, updated_at=now)
    for row in rows:
        refresh_order_commission(row.order)
        _settlement_event(row.order, f"台數獎金結算：{rule}／{period.label}，本單 {money(row.amount)}"
                          f"（{len(rows)} 台，達 {row.minimum_quantity} 台門檻），加進傭金支出，另外發放給車行", actor_name)
    return settlement


@transaction.atomic
def cancel_settlement(rule_id, period_id, dealer_id, actor_name, *, now=None):
    """取消結算：各單獎金從傭金支出移除、回到試算；已勾「已給付」的要先取消給付。"""
    from sales.reporting.payout_models import DealerPayoutEntry

    now = now or timezone.now()
    rules = _lock_rules([rule_id])
    settlement = (VolumeBonusSettlement.objects.select_for_update(of=("self",))
                  .filter(rule_id=rule_id, period_id=period_id, dealer_id=dealer_id, cancelled_at__isnull=True).first())
    if not rules or settlement is None:
        raise ValidationError("這一組沒有有效的結算，請重新整理。")
    if DealerPayoutEntry.objects.filter(source_key=settlement.source_key, paid=True).exists():
        raise ValidationError("這筆台數獎金已勾「已給付」，請先取消已給付，再取消結算。")
    rule = rules[0]
    rows = list(OrderVolumeBonus.objects.filter(rule_id=rule_id, period_id=period_id, dealer_id=dealer_id,
                                                posted_at__isnull=False).select_related("order"))
    settlement.cancelled_at = now
    settlement.cancelled_by = actor_name
    settlement.save(update_fields=["cancelled_at", "cancelled_by", "updated_at"])
    OrderVolumeBonus.objects.filter(pk__in=[row.pk for row in rows]).update(posted_at=None, updated_at=now)
    for row in rows:
        refresh_order_commission(row.order)
        _settlement_event(row.order, f"取消台數獎金結算：{rule}／{settlement.period.label}，"
                          f"本單 {money(row.amount)} 從傭金支出移除，回到試算", actor_name)
    # 回到試算後依目前資料重算一次（結算後有變的組，這時才反映新台數）。
    _recompute_scope(rule, settlement.period, settlement.dealer, now, {})
    return settlement
