"""車行傭金／獎金給付追蹤（T-150 方案 A，使用者 2026-11-11 選定）。

- 應付項目每次即時計算，不另存應付帳；`DealerPayoutEntry` 只記勾選、給付當下快照與備註。
- 一個應付項目一列：車行 × 訂單 × 項目（傭金、每個實物品項）；台數獎金每期 × 每家車行 × 每條規則一列。
- 只列領牌日 `PAYOUT_START_DATE`（含）以後、已完成領牌的車行單；取消、例外結案（含退車）、刪除的單不列。
  例外：Excel 匯入的車行單（T-275，使用者 2026-11-21 選 A）領牌日更早也列傭金，程式判定「匯入前已結清」：
  不寫給付紀錄、不算未給付；使用者可個別「改回未給付」（這時才建立紀錄）。匯入單的傭金＝Excel 四欄加總
  （`LEGACY_COMMISSION_FIELDS`），不重算。台數獎金、實物獎勵不放寬。
  例外：車行實物獎勵依訂單成立日預先觸發（T-176，使用者 2026-11-14），尚未確認領牌的單也列、也能勾已給付，
  判斷日改看訂單成立日。
- 已給付後金額變了：不自動取消，標「金額有變」，由使用者「確認差額」。來源消失：列在「來源已不存在」。
  實物獎勵因領牌日不符被撤銷資格（訂單仍有效）時標「資格撤銷・待追回」，由使用者按「已追回」或「不追回」結案。
- 勾「已給付」不影響車行結算、掛帳、淨利與收支帳本。
- 台數獎金（T-203，使用者 2026-11-17 選 C）：期間結束後列為「待結算」，在這頁按「結算」（規則×期間×車行一組）
  才加進各單傭金支出、淨利跟著反映；結算後顯示「待發放」，付給車行後勾「已給付」。不扣任何應收或掛帳。

來源：傭金 `OrderOperationsProfile`、實物 T-149 `OrderDealerRewardLine`、台數獎金 T-148 `OrderVolumeBonus`
＋ T-203 `VolumeBonusSettlement`。
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
# T-275：匯入單付給車行的錢＝Excel 這四欄加總（照原紀錄，不重算）；山葉、友善車行獎金「收入」是本店收入，不列。
LEGACY_COMMISSION_FIELDS = (
    ("dealer_commission_expense", "車行傭金"),
    ("friendly_dealer_bonus_expense", "友善車行獎金"),
    ("first_sale_bonus_expense", "首賣獎金"),
    ("volume_bonus_expense", "台數獎金"),
)
EXCLUDED_STATUSES = ("draft", "cancel_refund_pending", "cancelled", "exception_closed")

KIND_LABELS = dict(DealerPayoutEntry.Kind.choices)
STATUS_LABELS = OrderedDict((
    ("unpaid", "未給付"),
    ("paid", "已給付"),
    ("changed", "給付後金額有變"),
    ("settle", "待結算"),
    ("estimate", "預估"),
    ("prior_settled", "匯入前已結清"),
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
    deduction_amount: Decimal = ZERO
    estimate: bool = False
    day: date | None = None
    period_label: str = ""
    details: list = field(default_factory=list)
    reward_name: str = ""
    pre_triggered: bool = False
    # T-275：領牌日早於 PAYOUT_START_DATE 的匯入車行單傭金；沒有給付紀錄時判定「匯入前已結清」。
    imported_before_start: bool = False
    # Excel 匯入單（含匯入後有人修改的）：已給付後不標「給付後金額有變」（使用者 2026-11-21：「不需要再改」）。
    imported: bool = False
    entry: DealerPayoutEntry | None = None
    # 台數獎金結算（T-203）：""＝不適用、"pending"＝期間已結束待結算、"settled"＝已結算。
    settle_state: str = ""
    settlement: object = None
    settle_changes: list = field(default_factory=list)
    scope: tuple = ()
    settle_info: dict = field(default_factory=dict)

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
    def prior_settled(self):
        """匯入前已結清：程式規則，不寫資料；使用者改回未給付後（有給付紀錄）就照一般流程。"""
        return self.imported_before_start and self.entry is None

    @property
    def settled(self):
        return self.paid or self.prior_settled

    @property
    def deduction(self):
        return self.deduction_amount > ZERO

    @property
    def separate_amount(self):
        return max(self.amount - self.deduction_amount, ZERO)

    @property
    def methods(self):
        """抵扣與另付可能並存（分期車行單：傭金先抵應向車行收的費用，其餘另付，T-154）；篩選兩邊都列。
        匯入前已結清的不屬於任何一種。"""
        if self.prior_settled:
            return ()
        if not self.deduction:
            return ("separate",)
        return ("deduction",) if not self.separate_amount else ("deduction", "separate")

    @property
    def method(self):
        return self.methods[0] if self.methods else "prior_settled"

    @property
    def method_label(self):
        if self.prior_settled:
            return STATUS_LABELS["prior_settled"]
        if len(self.methods) > 1:
            return f"抵扣 ${self.deduction_amount:,.0f}／另付 ${self.separate_amount:,.0f}"
        return METHOD_LABELS[self.method]

    @property
    def is_quantity(self):
        return self.quantity is not None

    @property
    def paid(self):
        return bool(self.entry and self.entry.paid)

    @property
    def changed(self):
        """已給付後金額或數量變了；匯入單不標（照人員改過的值，不需要再改）。"""
        if not self.paid or self.imported:
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
        if self.prior_settled:
            return "prior_settled"
        if self.settle_state == "pending":
            return "settle"
        if self.changed:
            return "changed"
        return "paid" if self.paid else "unpaid"

    @property
    def status_label(self):
        if self.status == "unpaid" and self.kind == DealerPayoutEntry.Kind.VOLUME_BONUS:
            return "待發放"
        return STATUS_LABELS[self.status]

    @property
    def pending_settle(self):
        return self.settle_state == "pending"

    @property
    def note(self):
        return self.entry.note if self.entry else ""

    @property
    def checkable(self):
        return not self.estimate and self.settle_state != "pending"


# ── 來源 ──────────────────────────────────────────────────────────────


def _payout_orders():
    from sales.models import SalesOrder

    from django.db.models import Q

    return (
        SalesOrder.objects.filter(
            Q(registration_date__gte=PAYOUT_START_DATE) | Q(legacy_snapshot__isnull=False),
            source_type=SalesOrder.SourceType.DEALER,
            registration_completed_at__isnull=False,
            registration_date__isnull=False,
        )
        .exclude(status__in=EXCLUDED_STATUSES)
        .select_related("source", "commission_recipient", "vehicle_model", "color", "operations", "legacy_snapshot")
        # 台數獎金、配件、其他費用整批預取，傭金與向車行收的計算不逐張查詢（T-281）。
        .prefetch_related("volume_bonuses", "accessories", "other_fees")
        .order_by("registration_date", "pk")
    )


def order_vehicle_label(order):
    return f"{order.vehicle_model.name} {order.color.label}".strip()


def deduction_amount(order, amount, profile=None):
    """傭金（不含台數獎金）裡已在「向車行收」扣掉的部分（`customer_receivable.dealer_account_due` 同一條件）。

    系統建立的車行現金單全額抵扣；系統建立的分期車行單只抵扣應向車行收的費用（扣訂金後），其餘另付（T-154）。
    """
    from sales.services.customer_receivable import dealer_account_due

    if not (order.cash_receivable_v2 and not hasattr(order, "legacy_snapshot")):
        return ZERO
    if order.payment_type != "installment":
        return amount
    due = dealer_account_due(order, profile)
    if due is None:
        return ZERO
    # due＝應向車行收的費用－傭金（扣訂金前），加回傭金就是要收的費用；訂金已收的部分不再抵扣。
    fees = due + amount - (order.deposit_amount or ZERO)
    return min(amount, max(fees, ZERO))


def _bonus_in_commission(order, profile):
    """傭金支出裡含的自動入帳台數獎金（T-148），另列「台數獎金」，傭金列要扣掉避免重複。
    人工傭金是總支出、不拆分；匯入單不含。"""
    from sales.services.dealer_commission import commission_volume_bonus

    return commission_volume_bonus(order, profile)


def _legacy_commission(profile):
    """匯入單付給車行的金額與組成（Excel 四欄，T-275）。"""
    parts = [(label, getattr(profile, name) or ZERO) for name, label in LEGACY_COMMISSION_FIELDS]
    parts = [(label, value) for label, value in parts if value]
    text = "＋".join(f"{label} ${value:,.0f}" for label, value in parts)
    return sum((value for _label, value in parts), ZERO), f"Excel：{text}" if text else ""


def commission_items(orders=None):
    """`orders` 給定時只算這些單（T-315 訂單頁用 `_payout_orders().filter(pk=…)`，條件不變）。"""
    items = []
    for order in (_payout_orders() if orders is None else orders):
        profile = getattr(order, "operations", None)
        dealer = order.effective_commission_recipient
        if profile is None or dealer is None:
            continue
        imported = hasattr(order, "legacy_snapshot")
        if imported:
            amount, breakdown = _legacy_commission(profile)
        else:
            amount, breakdown = (profile.dealer_commission_expense or ZERO) - _bonus_in_commission(order, profile), ""
        if amount <= ZERO:
            continue
        items.append(PayoutItem(
            source_key=f"commission:order:{order.pk}",
            kind=DealerPayoutEntry.Kind.COMMISSION,
            dealer=dealer,
            label=f"{order_vehicle_label(order)} 傭金",
            amount=amount,
            order=order,
            deduction_amount=deduction_amount(order, amount, profile),
            day=order.registration_date,
            period_label=breakdown,
            imported_before_start=imported and order.registration_date < PAYOUT_START_DATE,
            imported=imported,
        ))
    return items


def _reward_key(line):
    """明細列重算時會刪掉重建（id 會變），用訂單＋活動＋品項當穩定代碼；沒有品項主檔時用名稱＋單位的摘要。"""
    if line.catalog_item_id:
        item = f"catalog:{line.catalog_item_id}"
    else:
        item = "name:" + hashlib.sha256(f"{line.name}|{line.unit}".encode("utf-8")).hexdigest()[:16]
    return f"reward:order:{line.order_id}:campaign:{line.campaign_id}:{item}"


def reward_items(order_id=None):
    """車行實物獎勵（T-149 `OrderDealerRewardLine`）：每張單 × 活動 × 品項一列，記數量與單位、不記金額。

    確認領牌前依訂單成立日預先觸發、確認後依實際領牌日（T-176）；確認後固定。尚未確認的單也列、也能勾，
    標「依訂單日・待領牌確認」。收款車行由明細記錄（含指定給車行的本店單）。一律「另付」。
    `order_id` 給定時只查這張單（T-315 訂單頁），條件不變。
    """
    from django.db.models import Q

    from sales.models import OrderDealerRewardLine, registration_confirmed_q

    confirmed = registration_confirmed_q("order__") & Q(order__registration_date__gte=PAYOUT_START_DATE)
    pre_triggered = Q(order__registration_completed_at__isnull=True, order__established_on__gte=PAYOUT_START_DATE)
    lines = (
        OrderDealerRewardLine.objects.filter(
            confirmed | pre_triggered,
            order__deleted_at__isnull=True,
            quantity__gt=0,
        )
        .exclude(order__status__in=EXCLUDED_STATUSES)
        .select_related("order", "order__vehicle_model", "order__color", "order__legacy_snapshot", "dealer")
        .order_by("order__registration_date", "order__established_on", "order_id", "campaign_id", "id")
    )
    if order_id is not None:
        lines = lines.filter(order_id=order_id)
    items = OrderedDict()
    for line in lines:
        key = _reward_key(line)
        if key in items:  # 同一活動重複列同一品項時合併數量
            items[key].quantity += line.quantity
            continue
        early = not line.order.registration_completed_at
        items[key] = PayoutItem(
            source_key=key,
            kind=DealerPayoutEntry.Kind.REWARD,
            dealer=line.dealer,
            label=f"{order_vehicle_label(line.order)} {line.name}（{line.campaign_name}）",
            quantity=line.quantity,
            unit=line.unit,
            order=line.order,
            day=line.order.reward_basis_date,
            period_label=f"{line.campaign_name}・依訂單日，待領牌確認" if early else line.campaign_name,
            reward_name=line.name,
            pre_triggered=early,
            imported=hasattr(line.order, "legacy_snapshot"),
        )
    return list(items.values())


def _period_text(period):
    """月、季用期間名稱；自訂期間直接寫起訖日（「自訂期間」看不出是哪一段）。"""
    from sales.models import DealerVolumeBonusRule

    if period.rule.period_type in {DealerVolumeBonusRule.PeriodType.MONTH, DealerVolumeBonusRule.PeriodType.QUARTER}:
        return period.label
    return f"{period.starts_on:%Y/%m/%d}－{period.ends_on:%m/%d}"


def volume_bonus_items(include_estimate=False, order_id=None):
    """台數獎金（`OrderVolumeBonus`）：每期 × 每家收款車行 × 每條規則一列，金額＝逐單合計。

    T-203（使用者 2026-11-17 選 C）：
    - 期間內是預估：只在 `include_estimate` 時灰色列出、不能勾。
    - 期間結束、還沒結算：預設列出、標「待結算」，可按「結算」；不能勾已給付、不算進未給付金額。
    - 已結算（有效的 `VolumeBonusSettlement`）：金額固定，標「待發放」，可勾已給付；結算後有變只標示。
    統計期間結束日早於 `PAYOUT_START_DATE` 的不列。另外發放給車行，不扣訂單應收（一律「另付」）。
    `order_id` 給定時只算含這張單的群組（T-315 訂單頁唯讀顯示），群組內容與金額照舊是整組。
    """
    from sales.models import OrderVolumeBonus, VolumeBonusSettlement
    from sales.services.volume_bonus import commission_note, period_ended, settlement_changes

    rows = (
        OrderVolumeBonus.objects.filter(period__ends_on__gte=PAYOUT_START_DATE, amount__gt=0)
        .select_related("rule", "period", "dealer", "order", "order__vehicle_model", "order__color")
        .order_by("period__starts_on", "rule_id", "dealer_id", "order__registration_date", "order_id")
    )
    settlement_rows = VolumeBonusSettlement.objects.filter(cancelled_at__isnull=True)
    if order_id is not None:
        scopes = set(rows.filter(order_id=order_id).values_list("rule_id", "period_id", "dealer_id"))
        if not scopes:
            return []
        rows = rows.filter(period_id__in={scope[1] for scope in scopes})
        settlement_rows = settlement_rows.filter(period_id__in={scope[1] for scope in scopes})
    else:
        scopes = None
    groups = OrderedDict()
    for row in rows:
        key = (row.rule_id, row.period_id, row.dealer_id)
        if scopes is None or key in scopes:
            groups.setdefault(key, []).append(row)
    settlements = {
        (item.rule_id, item.period_id, item.dealer_id): item
        for item in settlement_rows.select_related("rule", "period", "dealer")
    } if groups else {}
    items = []
    for (rule_id, period_id, dealer_id), members in groups.items():
        settlement = settlements.get((rule_id, period_id, dealer_id))
        if settlement:
            # 已結算：只算結算時固定的列（posted_at 有值）。
            members = [row for row in members if row.posted_at] or members
            state = "settled"
        elif period_ended(members[0].period):
            state = "pending"
        else:
            state = ""
        estimate = not settlement and state != "pending"
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
            settle_state=state,
            settlement=settlement,
            settle_changes=settlement_changes(settlement) if settlement else [],
            scope=(rule_id, period_id, dealer_id),
            settle_info={"rule": first.rule, "period": _period_text(first.period), "count": len(members),
                         "minimum": first.minimum_quantity, "per_vehicle": first.amount},
        ))
    return items


def _attach_entries(items):
    entries = DealerPayoutEntry.objects.in_bulk([item.source_key for item in items], field_name="source_key")
    for item in items:
        item.entry = entries.get(item.source_key)
    return items


def collect_items(*, include_estimate=False):
    return _attach_entries(commission_items() + reward_items() + volume_bonus_items(include_estimate))


def order_items(order):
    """只算這張單的應付項目（T-315 訂單頁）：傭金、每個活動×品項的實物獎勵，加上含這張單、已結算的台數獎金群組。

    條件與 `collect_items()` 完全相同（同一組函式只加上訂單篩選），不重算全公司。台數獎金是整批（規則×期間×車行），
    只給訂單頁顯示；勾選由 `set_order_paid` 擋下。
    """
    bonuses = [item for item in volume_bonus_items(order_id=order.pk) if item.settle_state == "settled"]
    return _attach_entries(
        commission_items(_payout_orders().filter(pk=order.pk)) + reward_items(order_id=order.pk) + bonuses
    )


def orphan_entries(items):
    """已給付但來源已不存在（退車、刪單、離開台數群組、規則刪除），且尚未確認處理。

    實物獎勵的訂單仍有效時，是領牌日不符被撤銷活動資格（T-176）：標 `revoked`，畫面列「資格撤銷・待追回」。
    """
    keys = {item.source_key for item in items}
    entries = [
        entry for entry in DealerPayoutEntry.objects.filter(paid=True, resolved_at__isnull=True)
        .select_related("dealer", "order").order_by("dealer__name", "pk")
        if entry.source_key not in keys
    ]
    for entry in entries:
        order = entry.order
        entry.revoked = bool(
            entry.kind == DealerPayoutEntry.Kind.REWARD and order is not None and order.deleted_at is None
            and order.status not in EXCLUDED_STATUSES
        )
    return entries


def current_item(source_key):
    return next((item for item in collect_items(include_estimate=True) if item.source_key == source_key), None)


# ── 訂單頁「車行獎勵」卡（T-315） ─────────────────────────────────────


def _not_listed_reason(order, kind):
    """卡片上有、給付頁沒有的項目，說明為什麼不能在這裡登記（條件同 `_payout_orders`、`reward_items`）。"""
    from sales.models import SalesOrder

    start = f"{PAYOUT_START_DATE:%Y/%m/%d}"
    if getattr(order, "deleted_at", None) or order.status in EXCLUDED_STATUSES:
        return "訂單已取消或結案，不列入給付追蹤"
    if kind == DealerPayoutEntry.Kind.COMMISSION:
        if order.source_type != SalesOrder.SourceType.DEALER:
            return "本店單指定給車行的傭金，給付頁目前不列"
        if not order.registration_completed_at or not order.registration_date:
            return "確認領牌後才能登記給付"
        if order.registration_date < PAYOUT_START_DATE:
            return f"領牌日早於 {start}，不列入給付追蹤"
    else:
        confirmed = bool(order.registration_completed_at)
        basis = order.registration_date if confirmed else order.established_on
        if basis and basis < PAYOUT_START_DATE:
            return f"{'領牌日' if confirmed else '訂單成立日'}早於 {start}，不列入給付追蹤"
    return "不列入給付追蹤"


def order_card(order, commission, rewards):
    """訂單頁「車行獎勵」卡逐項列（T-315，使用者選 A）：傭金、台數獎金、每個活動×品項各一列。

    `commission`＝`order_commission_display()`、`rewards`＝`order_dealer_rewards()`（卡片原本的兩份資料，金額照舊）。
    傭金列＝傭金支出扣掉已結算台數獎金；台數獎金另列、整批發放只顯示。可勾的列都對到給付頁同一個 `source_key`。
    """
    items = order_items(order)
    by_key = {item.source_key: item for item in items}
    rows = []
    included_bonus = commission["volume_bonus"] if commission else ZERO
    if commission and commission["amount"] - included_bonus > ZERO:
        item = by_key.get(f"commission:order:{order.pk}")
        amount = commission["amount"] - included_bonus
        rows.append({
            "kind": DealerPayoutEntry.Kind.COMMISSION, "name": "傭金", "item": item,
            "state": commission["state"], "state_label": commission["state_label"],
            "amount": amount,
            # 匯入單給付頁金額＝Excel 四欄加總（T-275），可能和傭金支出不同，列出來免得對不起來。
            "payout_amount": item.amount if item and item.amount != amount else None,
            "reason": "" if item else _not_listed_reason(order, DealerPayoutEntry.Kind.COMMISSION),
        })
    bonus_rows = []
    for item in items:
        if item.kind != DealerPayoutEntry.Kind.VOLUME_BONUS:
            continue
        share = sum((detail["amount"] for detail in item.details if detail["number"] == order.number), ZERO)
        if share <= ZERO:  # 結算後才加進群組、沒有算進這次結算的單，台數獎金不在它的傭金支出裡
            continue
        bonus_rows.append({"kind": item.kind, "name": "台數獎金", "item": item, "amount": share, "batch": True})
    reward_rows = OrderedDict()
    for line in (rewards or {}).get("lines", []):
        key = _reward_key(line)
        if key in reward_rows:  # 同一活動重複列同一品項，與給付頁一樣合併數量
            reward_rows[key]["quantity"] += line.quantity
            continue
        item = by_key.get(key)
        reward_rows[key] = {
            "kind": DealerPayoutEntry.Kind.REWARD, "name": line.name, "campaign": line.campaign_name,
            "item": item, "quantity": line.quantity, "unit": line.unit,
            "reason": "" if item else (
                "數量為 0，不需給付" if line.quantity <= 0 else _not_listed_reason(order, DealerPayoutEntry.Kind.REWARD)
            ),
        }
    checkable = [row for row in rows + list(reward_rows.values()) if row["item"] is not None]
    dealer = next((row["item"].dealer for row in checkable), None) or (commission or {}).get("recipient")
    days = [row["item"].day for row in checkable if row["item"].day]
    return {
        "commission_rows": rows + bonus_rows,
        "reward_rows": list(reward_rows.values()),
        "paid_count": sum(1 for row in checkable if row["item"].settled),
        "total": len(checkable),
        "included_bonus": included_bonus,
        "has_bonus": bool(bonus_rows),
        "dealer": dealer,
        "start": min(days) if days else None,
        "end": max(days) if days else None,
        "payout_start": PAYOUT_START_DATE,
    }


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
        if method and method not in item.methods:
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
            "settle_amount": ZERO, "settle_count": 0, "settle_changed": 0, "prior_settled_count": 0,
        })
        group["count"] += 1
        if item.kind == DealerPayoutEntry.Kind.VOLUME_BONUS:
            group["bonuses"].append(item)
        else:
            row = group["orders"].setdefault(item.order.pk, {"order": item.order, "items": []})
            row["items"].append(item)
        if item.estimate:
            continue
        if item.pending_settle:
            group["settle_amount"] += item.amount
            group["settle_count"] += 1
            continue
        if item.prior_settled:
            group["prior_settled_count"] += 1
            continue
        if item.changed:
            group["attention"] += 1
        if item.settle_changes:
            group["settle_changed"] += 1
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
            row["all_paid"] = all(item.settled for item in row["items"])
        group["unpaid_goods"] = [
            {"label": label, "unit": unit, "quantity": _quantity_text(quantity)}
            for (label, unit), quantity in group["unpaid_goods"].items()
        ]
        result.append(group)
    return result


def totals(items):
    counted = [item for item in items if not item.estimate and not item.pending_settle and not item.prior_settled]
    pending = [item for item in items if item.pending_settle]
    prior = [item for item in items if item.prior_settled]
    paid_amount = sum((i.paid_snapshot_amount for i in counted), ZERO)
    prior_settled_amount = sum((i.amount for i in prior), ZERO)
    return {
        "unpaid_amount": sum((i.amount for i in counted if not i.paid and not i.is_quantity), ZERO),
        "paid_amount": paid_amount,
        # 摘要「已給付金額」＝一般已給付＋匯入前已結清（T-277，使用者 2026-11-21「已給付金額應該要全部加總」）。
        "paid_total_amount": paid_amount + prior_settled_amount,
        "unpaid_count": sum(1 for i in counted if not i.paid),
        "changed_count": sum(1 for i in counted if i.changed),
        "settle_changed_count": sum(1 for i in counted if i.settle_changes),
        "settle_amount": sum((i.amount for i in pending), ZERO),
        "settle_count": len(pending),
        "prior_settled_count": len(prior),
        "prior_settled_amount": prior_settled_amount,
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
        if item.pending_settle:
            raise ValidationError(f"{item.dealer.name} {item.label} 還沒結算，請先按「結算」再勾選給付。")
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
def set_paid(source_keys, paid, actor_name, *, items=None):
    """勾選或取消已給付；批次時任何一筆不合格就整批不寫入。回傳實際改變的筆數。

    `items` 給定時（T-315 訂單頁傳 `order_items(order)`）只在這些項目裡找，不重算全公司；其餘邏輯相同。
    """
    keys = list(dict.fromkeys(source_keys))
    if not keys:
        raise ValidationError("請先勾選要登記的項目。")
    items_by_key = {item.source_key: item for item in (collect_items() if items is None else items)}
    items = [_require_item(key, items_by_key) for key in keys]
    changed = 0
    for item in sorted(items, key=lambda row: row.source_key):
        if item.prior_settled:
            # 匯入前已結清（T-275）：勾已給付不寫入；改回未給付才建立紀錄，之後照一般流程。
            if not paid:
                entry = _locked_entry(item)
                _event(entry, DealerPayoutEvent.Action.UNPAID, actor_name, item=item)
                changed += 1
            continue
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
def set_order_paid(order, source_keys, paid, actor_name):
    """訂單頁「車行獎勵」卡逐項勾選（T-315，使用者選 A）：寫入與給付頁同一筆 `DealerPayoutEntry`。

    只接受這張單自己的傭金與實物獎勵；台數獎金是多張單合成一筆，勾或取消會連帶改到同批其他單，一律拒絕。
    """
    items = order_items(order)
    own = {item.source_key: item for item in items}
    for key in dict.fromkeys(source_keys):
        item = own.get(key)
        if item is not None and item.kind == DealerPayoutEntry.Kind.VOLUME_BONUS:
            raise ValidationError("台數獎金是整批發放（同車行、同期間的多張單合成一筆），請到「車行傭金／獎金給付」頁勾選。")
        if item is None and key.startswith("volume_bonus:"):
            raise ValidationError("台數獎金是整批發放，請到「車行傭金／獎金給付」頁勾選。")
    return set_paid(source_keys, paid, actor_name,
                    items=[item for item in items if item.kind != DealerPayoutEntry.Kind.VOLUME_BONUS])


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
        if item.prior_settled:
            raise ValidationError("匯入前已結清的項目不能加備註；確定其實沒付，請先改回未給付。")
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


RESOLVE_OUTCOMES = {"recovered": "已追回", "waived": "不追回"}


@transaction.atomic
def resolve_orphan(entry_id, actor_name, outcome=""):
    """來源消失確認處理；資格撤銷的實物獎勵用 outcome 記「已追回」或「不追回」（T-176，寫在處理事件）。"""
    if outcome and outcome not in RESOLVE_OUTCOMES:
        raise ValidationError("請選擇已追回或不追回。")
    entry = DealerPayoutEntry.objects.select_for_update(of=("self",)).filter(pk=entry_id).first()
    if entry is None or not entry.paid or entry.resolved_at:
        raise ValidationError("這筆已處理或不存在，請重新整理。")
    if current_item(entry.source_key) is not None:
        raise ValidationError("這個項目仍在給付列表，不需要處理。")
    entry.resolved_at = timezone.now()
    entry.resolved_by = actor_name
    entry.save(update_fields=["resolved_at", "resolved_by", "updated_at"])
    _event(entry, DealerPayoutEvent.Action.RESOLVE, actor_name, note_after=RESOLVE_OUTCOMES.get(outcome, ""))
