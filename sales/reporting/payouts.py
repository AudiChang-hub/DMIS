"""車行傭金／獎金給付追蹤（T-150 方案 A，使用者 2026-11-11 選定）。

- 應付項目每次即時計算，不另存應付帳；`DealerPayoutEntry` 只記勾選、給付當下快照與備註。
- 一個應付項目一列：車行 × 訂單 × 項目（傭金、每個實物品項）；台數獎金每期 × 每家車行 × 每條規則一列。
- 只列領牌日 `PAYOUT_START_DATE`（含）以後、已完成領牌的車行單；取消、例外結案（含退車）、刪除的單不列。
- 已給付後金額變了：不自動取消，標「金額有變」，由使用者「確認差額」。來源消失：列在「來源已不存在」。
- 不影響車行結算、掛帳、淨利與收支帳本。

來源：傭金 `OrderOperationsProfile`、實物 T-149 `OrderDealerRewardLine`、台數獎金 T-148 `OrderVolumeBonus`。
"""
import hashlib
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .payout_models import DealerPayoutEntry, DealerPayoutEvent

# 使用者 2026-11-11：領牌日 2026-10-05（含）以後才列；之前多為 Excel 匯入的歷史單，推定已付清。
PAYOUT_START_DATE = date(2026, 10, 5)
ZERO = Decimal("0")
EXCLUDED_STATUSES = ("draft", "cancel_refund_pending", "cancelled", "exception_closed")

KIND_LABELS = dict(DealerPayoutEntry.Kind.choices)
STATUS_LABELS = OrderedDict((
    ("unpaid", "未給付"),
    ("paid", "已給付"),
    ("changed", "給付後金額有變"),
    ("estimate", "預估"),
))
METHOD_LABELS = OrderedDict((("deduction", "抵扣應收"), ("separate", "另付")))


@dataclass
class PayoutItem:
    source_key: str
    kind: str
    dealer: object
    label: str
    amount: Decimal = ZERO
    quantity: Decimal | None = None
    unit: str = ""
    order: object = None
    deduction: bool = False
    estimate: bool = False
    day: date | None = None
    period_label: str = ""
    details: list = field(default_factory=list)
    reward_name: str = ""
    entry: DealerPayoutEntry | None = None

    @property
    def kind_label(self):
        return KIND_LABELS[self.kind]

    @property
    def short_label(self):
        """畫面上訂單已列車型與車色，傭金列只寫「傭金」；CSV 與來源消失清單用完整 label。"""
        if self.kind == DealerPayoutEntry.Kind.COMMISSION:
            return "傭金"
        if self.kind == DealerPayoutEntry.Kind.REWARD:
            return self.reward_name or self.label
        return self.label.removeprefix("台數獎金 ")

    @property
    def paid_snapshot_amount(self):
        """已給付金額以給付當下的快照計（金額事後變動時，已付的是舊金額）。"""
        return (self.entry.paid_amount or ZERO) if self.paid and not self.is_quantity else ZERO

    @property
    def method(self):
        return "deduction" if self.deduction else "separate"

    @property
    def method_label(self):
        return METHOD_LABELS[self.method]

    @property
    def is_quantity(self):
        return self.quantity is not None

    @property
    def paid(self):
        return bool(self.entry and self.entry.paid)

    @property
    def changed(self):
        """已給付後金額或數量變了。"""
        if not self.paid:
            return False
        if self.is_quantity:
            return self.entry.paid_quantity != self.quantity
        return self.entry.paid_amount != self.amount

    @property
    def difference(self):
        if not self.changed or self.is_quantity:
            return None
        return self.amount - (self.entry.paid_amount or ZERO)

    @property
    def status(self):
        if self.estimate:
            return "estimate"
        if self.changed:
            return "changed"
        return "paid" if self.paid else "unpaid"

    @property
    def status_label(self):
        return STATUS_LABELS[self.status]

    @property
    def note(self):
        return self.entry.note if self.entry else ""

    @property
    def checkable(self):
        return not self.estimate


# ── 來源 ──────────────────────────────────────────────────────────────


def _payout_orders():
    from sales.models import SalesOrder

    return (
        SalesOrder.objects.filter(
            source_type=SalesOrder.SourceType.DEALER,
            registration_date__gte=PAYOUT_START_DATE,
            registration_completed_at__isnull=False,
        )
        .exclude(status__in=EXCLUDED_STATUSES)
        .select_related("source", "commission_recipient", "vehicle_model", "color", "operations")
        .order_by("registration_date", "pk")
    )


def order_vehicle_label(order):
    return f"{order.vehicle_model.name} {order.color.name}".strip()


def is_deduction_order(order):
    """系統建立的車行現金單：傭金已在「向車行收」扣掉（`customer_receivable.dealer_cash_credit` 同一條件）。"""
    return bool(
        order.payment_type != "installment" and order.cash_receivable_v2 and not hasattr(order, "legacy_snapshot")
    )


def _bonus_in_commission(order, profile):
    """傭金支出裡含的自動入帳台數獎金（T-148），另列「台數獎金」，傭金列要扣掉避免重複。
    人工傭金是總支出、不拆分；匯入單不含。"""
    from sales.services.dealer_commission import commission_volume_bonus

    return commission_volume_bonus(order, profile)


def commission_items():
    items = []
    for order in _payout_orders():
        profile = getattr(order, "operations", None)
        dealer = order.effective_commission_recipient
        if profile is None or dealer is None:
            continue
        amount = (profile.dealer_commission_expense or ZERO) - _bonus_in_commission(order, profile)
        if amount <= ZERO:
            continue
        items.append(PayoutItem(
            source_key=f"commission:order:{order.pk}",
            kind=DealerPayoutEntry.Kind.COMMISSION,
            dealer=dealer,
            label=f"{order_vehicle_label(order)} 傭金",
            amount=amount,
            order=order,
            deduction=is_deduction_order(order),
            day=order.registration_date,
        ))
    return items


def _reward_key(line):
    """明細列重算時會刪掉重建（id 會變），用訂單＋活動＋品項當穩定代碼；沒有品項主檔時用名稱＋單位的摘要。"""
    if line.catalog_item_id:
        item = f"catalog:{line.catalog_item_id}"
    else:
        item = "name:" + hashlib.sha1(f"{line.name}|{line.unit}".encode("utf-8")).hexdigest()[:16]
    return f"reward:order:{line.order_id}:campaign:{line.campaign_id}:{item}"


def reward_items():
    """車行實物獎勵（T-149 `OrderDealerRewardLine`）：每張單 × 活動 × 品項一列，記數量與單位、不記金額。

    依實際領牌日套用、領牌完成後固定；收款車行由明細記錄（含指定給車行的本店單）。一律「另付」。
    """
    from sales.models import OrderDealerRewardLine

    lines = (
        OrderDealerRewardLine.objects.filter(
            order__registration_date__gte=PAYOUT_START_DATE,
            order__registration_completed_at__isnull=False,
            order__deleted_at__isnull=True,
            quantity__gt=0,
        )
        .exclude(order__status__in=EXCLUDED_STATUSES)
        .select_related("order", "order__vehicle_model", "order__color", "dealer")
        .order_by("order__registration_date", "order_id", "campaign_id", "id")
    )
    items = OrderedDict()
    for line in lines:
        key = _reward_key(line)
        if key in items:  # 同一活動重複列同一品項時合併數量
            items[key].quantity += line.quantity
            continue
        items[key] = PayoutItem(
            source_key=key,
            kind=DealerPayoutEntry.Kind.REWARD,
            dealer=line.dealer,
            label=f"{order_vehicle_label(line.order)} {line.name}（{line.campaign_name}）",
            quantity=line.quantity,
            unit=line.unit,
            order=line.order,
            day=line.order.registration_date,
            period_label=line.campaign_name,
            reward_name=line.name,
        )
    return list(items.values())


def _period_text(period):
    """月、季用期間名稱；自訂期間直接寫起訖日（「自訂期間」看不出是哪一段）。"""
    from sales.models import DealerVolumeBonusRule

    if period.rule.period_type in {DealerVolumeBonusRule.PeriodType.MONTH, DealerVolumeBonusRule.PeriodType.QUARTER}:
        return period.label
    return f"{period.starts_on:%Y/%m/%d}－{period.ends_on:%m/%d}"


def volume_bonus_items(include_estimate=False):
    """台數獎金（T-148 `OrderVolumeBonus`）：每期 × 每家收款車行 × 每條規則一列，金額＝逐單合計。

    期間結束、全部入帳（`posted_at`）才列入且可勾選；期間內的預估只在 `include_estimate` 時灰色列出、不能勾。
    統計期間結束日早於 `PAYOUT_START_DATE` 的不列。另外付給車行，不扣訂單應收（一律「另付」）。
    """
    from sales.models import OrderVolumeBonus
    from sales.services.volume_bonus import commission_note

    rows = (
        OrderVolumeBonus.objects.filter(period__ends_on__gte=PAYOUT_START_DATE, amount__gt=0)
        .select_related("rule", "period", "dealer", "order", "order__vehicle_model", "order__color")
        .order_by("period__starts_on", "rule_id", "dealer_id", "order__registration_date", "order_id")
    )
    groups = OrderedDict()
    for row in rows:
        groups.setdefault((row.rule_id, row.period_id, row.dealer_id), []).append(row)
    items = []
    for (rule_id, period_id, dealer_id), members in groups.items():
        estimate = any(row.posted_at is None for row in members)
        if estimate and not include_estimate:
            continue
        first = members[0]
        items.append(PayoutItem(
            source_key=f"volume_bonus:rule:{rule_id}:period:{period_id}:dealer:{dealer_id}",
            kind=DealerPayoutEntry.Kind.VOLUME_BONUS,
            dealer=first.dealer,
            label=f"台數獎金 {first.rule}",
            amount=sum((row.amount for row in members), ZERO),
            estimate=estimate,
            day=first.period.ends_on,
            period_label=f"{_period_text(first.period)}・{len(members)} 台，達 {first.minimum_quantity} 台門檻",
            details=[{
                "number": row.order.number,
                "label": order_vehicle_label(row.order),
                "amount": row.amount,
                "note": commission_note(row.order),
            } for row in members],
        ))
    return items


def collect_items(*, include_estimate=False):
    items = commission_items() + reward_items() + volume_bonus_items(include_estimate)
    entries = DealerPayoutEntry.objects.in_bulk([item.source_key for item in items], field_name="source_key")
    for item in items:
        item.entry = entries.get(item.source_key)
    return items


def orphan_entries(items):
    """已給付但來源已不存在（退車、刪單、離開台數群組、規則刪除），且尚未確認處理。"""
    keys = {item.source_key for item in items}
    return [
        entry for entry in DealerPayoutEntry.objects.filter(paid=True, resolved_at__isnull=True)
        .select_related("dealer", "order").order_by("dealer__name", "pk")
        if entry.source_key not in keys
    ]


def current_item(source_key):
    return next((item for item in collect_items(include_estimate=True) if item.source_key == source_key), None)


# ── 篩選與彙總 ────────────────────────────────────────────────────────


def filter_items(items, *, dealer_id=None, start=None, end=None, status="", kind="", method=""):
    result = []
    for item in items:
        if dealer_id and item.dealer.pk != dealer_id:
            continue
        if start and (item.day is None or item.day < start):
            continue
        if end and (item.day is None or item.day > end):
            continue
        if status and item.status != status:
            continue
        if kind and item.kind != kind:
            continue
        if method and item.method != method:
            continue
        result.append(item)
    return result


def _quantity_text(quantity):
    return f"{quantity.normalize():f}" if quantity is not None else ""


def summarize(items):
    """每家車行：未給付金額、已給付金額、未給付實物（同名同單位加總），以及依訂單分組。"""
    dealers = OrderedDict()
    for item in sorted(items, key=lambda row: (row.dealer.name, row.kind == "volume_bonus", row.day or date.min,
                                               getattr(row.order, "pk", 0), row.source_key)):
        group = dealers.setdefault(item.dealer.pk, {
            "dealer": item.dealer, "orders": OrderedDict(), "bonuses": [],
            "unpaid_amount": ZERO, "paid_amount": ZERO, "unpaid_goods": OrderedDict(), "count": 0, "attention": 0,
        })
        group["count"] += 1
        if item.kind == DealerPayoutEntry.Kind.VOLUME_BONUS:
            group["bonuses"].append(item)
        else:
            row = group["orders"].setdefault(item.order.pk, {"order": item.order, "items": []})
            row["items"].append(item)
        if item.estimate:
            continue
        if item.changed:
            group["attention"] += 1
        if item.is_quantity:
            if not item.paid:
                key = (item.short_label, item.unit)
                group["unpaid_goods"][key] = group["unpaid_goods"].get(key, ZERO) + item.quantity
        elif item.paid:
            group["paid_amount"] += item.paid_snapshot_amount
        else:
            group["unpaid_amount"] += item.amount
    result = []
    for group in dealers.values():
        group["orders"] = list(group["orders"].values())
        for row in group["orders"]:
            row["all_paid"] = all(item.paid for item in row["items"])
        group["unpaid_goods"] = [
            {"label": label, "unit": unit, "quantity": _quantity_text(quantity)}
            for (label, unit), quantity in group["unpaid_goods"].items()
        ]
        result.append(group)
    return result


def totals(items):
    counted = [item for item in items if not item.estimate]
    return {
        "unpaid_amount": sum((i.amount for i in counted if not i.paid and not i.is_quantity), ZERO),
        "paid_amount": sum((i.paid_snapshot_amount for i in counted), ZERO),
        "unpaid_count": sum(1 for i in counted if not i.paid),
        "changed_count": sum(1 for i in counted if i.changed),
        "dealer_count": len({i.dealer.pk for i in items}),
        "item_count": len(items),
    }


# ── 寫入 ──────────────────────────────────────────────────────────────


def _snapshot(entry, item):
    entry.kind = item.kind
    entry.dealer = item.dealer
    entry.order = item.order
    entry.label = item.label[:200]


def _locked_entry(item):
    """取得並鎖住該項目的給付紀錄；兩人同時建立時以唯一鍵擋下後改鎖既有那筆。"""
    queryset = DealerPayoutEntry.objects.select_for_update(of=("self",))
    entry = queryset.filter(source_key=item.source_key).first()
    if entry is not None:
        return entry
    try:
        with transaction.atomic():
            entry = DealerPayoutEntry(source_key=item.source_key)
            _snapshot(entry, item)
            entry.save()
            return entry
    except IntegrityError:
        return queryset.get(source_key=item.source_key)


def _event(entry, action, actor_name, *, item=None, note_before="", note_after=""):
    DealerPayoutEvent.objects.create(
        entry=entry, action=action, actor_name=actor_name,
        amount=None if item is None or item.is_quantity else item.amount,
        quantity=item.quantity if item is not None else None,
        note_before=note_before, note_after=note_after,
    )


def _require_item(source_key, items_by_key):
    item = items_by_key.get(source_key)
    if item is None:
        raise ValidationError("這個項目已不在給付列表（訂單可能已退車、刪除或金額歸零），請重新整理。")
    if not item.checkable:
        raise ValidationError(f"{item.dealer.name} {item.label} 期間還沒結束，是預估金額，不能勾選給付。")
    return item


def _mark_paid(entry, item, actor_name, action=DealerPayoutEvent.Action.PAID):
    _snapshot(entry, item)
    entry.paid = True
    entry.paid_amount = None if item.is_quantity else item.amount
    entry.paid_quantity = item.quantity
    entry.paid_unit = item.unit
    entry.paid_at = timezone.now()
    entry.paid_by = actor_name
    entry.save()
    _event(entry, action, actor_name, item=item)


@transaction.atomic
def set_paid(source_keys, paid, actor_name):
    """勾選或取消已給付；批次時任何一筆不合格就整批不寫入。回傳實際改變的筆數。"""
    keys = list(dict.fromkeys(source_keys))
    if not keys:
        raise ValidationError("請先勾選要登記的項目。")
    items_by_key = {item.source_key: item for item in collect_items()}
    items = [_require_item(key, items_by_key) for key in keys]
    changed = 0
    for item in sorted(items, key=lambda row: row.source_key):
        if not paid and item.entry is None:
            continue
        entry = _locked_entry(item)
        if paid and not entry.paid:
            _mark_paid(entry, item, actor_name)
            changed += 1
        elif not paid and entry.paid:
            entry.paid = False
            entry.paid_at = None
            entry.paid_by = ""
            entry.save(update_fields=["paid", "paid_at", "paid_by", "updated_at"])
            _event(entry, DealerPayoutEvent.Action.UNPAID, actor_name, item=item)
            changed += 1
    return changed


@transaction.atomic
def confirm_difference(source_key, actor_name):
    """給付後金額有變，補付或收回後確認：以目前金額重新記一次給付。"""
    item = _require_item(source_key, {item.source_key: item for item in collect_items()})
    entry = _locked_entry(item)
    item.entry = entry
    if not item.changed:
        raise ValidationError("這個項目的金額沒有變動，不需要確認差額。")
    _mark_paid(entry, item, actor_name, DealerPayoutEvent.Action.CONFIRM_DIFFERENCE)


@transaction.atomic
def save_note(source_key, note, actor_name):
    note = (note or "").strip()
    if len(note) > 500:
        raise ValidationError("備註最多 500 字。")
    entry = DealerPayoutEntry.objects.select_for_update(of=("self",)).filter(source_key=source_key).first()
    if entry is None:
        item = current_item(source_key)
        if item is None:
            raise ValidationError("這個項目已不在給付列表，請重新整理。")
        if not note:
            return False
        entry = _locked_entry(item)
    if entry.note == note:
        return False
    before = entry.note
    entry.note = note
    entry.save(update_fields=["note", "updated_at"])
    _event(entry, DealerPayoutEvent.Action.NOTE, actor_name, note_before=before, note_after=note)
    return True


@transaction.atomic
def resolve_orphan(entry_id, actor_name):
    entry = DealerPayoutEntry.objects.select_for_update(of=("self",)).filter(pk=entry_id).first()
    if entry is None or not entry.paid or entry.resolved_at:
        raise ValidationError("這筆已處理或不存在，請重新整理。")
    if current_item(entry.source_key) is not None:
        raise ValidationError("這個項目仍在給付列表，不需要處理。")
    entry.resolved_at = timezone.now()
    entry.resolved_by = actor_name
    entry.save(update_fields=["resolved_at", "resolved_by", "updated_at"])
    _event(entry, DealerPayoutEvent.Action.RESOLVE, actor_name)
