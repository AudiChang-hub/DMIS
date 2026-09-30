"""收款帳本：已確認收款不可改寫，更正與退款一律以負向紀錄入帳。"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

ZERO = Decimal("0")
KINDS = ("customer", "lender")


def ledger_totals(order, records=None):
    """依款項分類彙總收款、沖銷、退款與淨實收；未確認金額另列，不計入淨額。"""
    from sales.models import PaymentRecord

    records = list(order.payment_records.all()) if records is None else list(records)
    totals = {kind: dict(received=ZERO, reversed=ZERO, refunded=ZERO, net=ZERO, unconfirmed=ZERO) for kind in KINDS}
    for record in records:
        bucket = totals[record.effective_receipt_kind]
        amount = record.received_amount or ZERO
        if not record.confirmed:
            if record.entry_type == PaymentRecord.EntryType.RECEIPT and amount > 0:
                bucket["unconfirmed"] += amount
            continue
        if record.entry_type == PaymentRecord.EntryType.REVERSAL:
            bucket["reversed"] -= amount
        elif record.entry_type == PaymentRecord.EntryType.REFUND:
            bucket["refunded"] -= amount
        else:
            bucket["received"] += amount
        bucket["net"] += amount
    return totals


def is_reversible(payment):
    from sales.models import PaymentRecord

    return bool(
        payment.pk and payment.confirmed and payment.entry_type == PaymentRecord.EntryType.RECEIPT
        and (payment.received_amount or ZERO) > 0 and not payment.reversal_entries.exists()
    )


def refundable_overpayment(order, kind="customer"):
    from .payment_summary import payment_summary

    return payment_summary(order)[f"{kind}_overpaid"]


def find_duplicate_receipt(payment, *, order=None, received_amount=None, received_on=None, kind=None):
    """同訂單、同分類、同金額、同日期且未被沖銷的已確認收款，視為可能重複登記。"""
    from sales.models import PaymentRecord

    order = order or payment.order
    amount = received_amount if received_amount is not None else payment.received_amount
    day = received_on if received_on is not None else payment.received_on
    kind = kind or payment.effective_receipt_kind
    if not amount or amount <= 0 or not day:
        return None
    candidates = PaymentRecord.objects.filter(
        order=order, entry_type=PaymentRecord.EntryType.RECEIPT, confirmed=True,
        received_amount=amount, received_on=day, reversal_entries__isnull=True,
    )
    if payment.pk:
        candidates = candidates.exclude(pk=payment.pk)
    return next((item for item in candidates if item.effective_receipt_kind == kind), None)


def _locked(order_id, payment_id=None):
    from sales.models import PaymentRecord, SalesOrder

    order = SalesOrder.objects.select_for_update().get(pk=order_id)
    payment = PaymentRecord.objects.select_for_update().get(pk=payment_id, order=order) if payment_id else None
    return order, payment


def _audit(order, *, actor_name, reason, changes, event_type, description):
    from sales.models import OrderChange, OrderEvent

    OrderChange.objects.create(order=order, reason=reason, changes=changes, actor_name=actor_name)
    OrderEvent.objects.create(order=order, event_type=event_type, description=description, actor_name=actor_name)


def _require_reason(reason):
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("請填寫原因。")
    return reason[:250]


@transaction.atomic
def reverse_payment(*, order_id, payment_id, actor_name, reason):
    """整筆沖銷登記錯誤的已確認收款；正確金額另行新增收款。"""
    from sales.models import PaymentRecord, SalesOrder

    reason = _require_reason(reason)
    order, payment = _locked(order_id, payment_id)
    if order.status in {SalesOrder.Status.CANCELLED, SalesOrder.Status.EXCEPTION_CLOSED}:
        raise ValidationError("已取消或結案的訂單帳務已結算，不能再沖銷。")
    if not is_reversible(payment):
        raise ValidationError("只能沖銷已確認且尚未沖銷的收款。")
    reversal = PaymentRecord.objects.create(
        order=order,
        entry_type=PaymentRecord.EntryType.REVERSAL,
        reverses=payment,
        item_name=f"沖銷：{payment.item_name}"[:160],
        receipt_kind=payment.effective_receipt_kind,
        received_amount=-payment.received_amount,
        received_on=timezone.localdate(),
        payment_method=payment.payment_method,
        confirmed=True,
        confirmed_by=actor_name,
        confirmed_at=timezone.now(),
        adjustment_reason=reason,
    )
    _audit(
        order, actor_name=actor_name, reason=reason, event_type="payment_reversed",
        changes={"沖銷收款": {"before": f"{payment.item_name} {payment.received_amount:,.0f} 元", "after": "已沖銷"}},
        description=f"沖銷 {payment.item_name} ${payment.received_amount:,.0f}；原因：{reason}",
    )
    return reversal


def create_refund_entry(order, *, kind, amount, actor_name, reason, method_label, refunded_on, reference, item_name):
    from sales.models import PaymentRecord

    return PaymentRecord.objects.create(
        order=order,
        entry_type=PaymentRecord.EntryType.REFUND,
        item_name=item_name,
        receipt_kind=kind,
        received_amount=-amount,
        received_on=refunded_on,
        payment_method=method_label,
        receiving_account=(reference or "")[:120],
        confirmed=True,
        confirmed_by=actor_name,
        confirmed_at=timezone.now(),
        adjustment_reason=reason,
    )


@transaction.atomic
def refund_overpayment(*, order_id, kind, amount, actor_name, reason, method_label, refunded_on, reference=""):
    """退還溢收；金額不得超過目前已確認淨實收超出應收的部分。"""
    reason = _require_reason(reason)
    if kind not in KINDS:
        raise ValidationError("款項分類不正確。")
    order, _payment = _locked(order_id)
    if order.is_cancelled_sale:
        raise ValidationError("取消中或已取消的訂單請由取消退款結算處理。")
    amount = Decimal(amount or 0)
    limit = refundable_overpayment(order, kind)
    if amount <= 0 or amount > limit:
        raise ValidationError(f"退款金額須大於 0 且不超過溢收 {limit:,.0f} 元。")
    record = create_refund_entry(
        order, kind=kind, amount=amount, actor_name=actor_name, reason=reason, method_label=method_label,
        refunded_on=refunded_on, reference=reference,
        item_name="退還溢收" if kind == "customer" else "退還分期公司溢撥",
    )
    _audit(
        order, actor_name=actor_name, reason=reason, event_type="overpayment_refunded",
        changes={"退還溢收": {"before": f"{limit:,.0f}", "after": f"{limit - amount:,.0f}"}},
        description=f"退還溢收 ${amount:,.0f}（{method_label}）；原因：{reason}",
    )
    return record


@transaction.atomic
def complete_cancellation_refund(order, *, actor_name, forfeited_amount, completed_on, method,
                                 reference="", proof=None, forfeit_reason=""):
    """取消結算：應退＝客戶已確認淨實收－沒收金額，退款以負向紀錄入帳。"""
    from sales.models import SalesOrder

    locked, _payment = _locked(order.pk)
    if locked.status != SalesOrder.Status.CANCEL_REFUND_PENDING:
        raise ValidationError("此訂單目前不在取消待退款狀態。")
    ledger = ledger_totals(locked)
    if ledger["customer"]["unconfirmed"] or ledger["lender"]["unconfirmed"]:
        raise ValidationError("尚有已登記但未確認的實收金額，請先確認或清除後再結算退款。")
    if ledger["lender"]["net"] > 0:
        raise ValidationError("分期公司已撥款，不能以取消結算。")
    received = ledger["customer"]["net"]
    forfeited = Decimal(forfeited_amount or 0)
    if forfeited < 0 or forfeited > received:
        raise ValidationError(f"沒收金額須介於 0 至已收 {received:,.0f} 元之間。")
    forfeit_reason = (forfeit_reason or "").strip()
    if forfeited and not forfeit_reason:
        raise ValidationError("有沒收金額時，請填寫沒收原因。")
    refund = received - forfeited
    method_label = dict(SalesOrder.PaymentMethod.choices).get(method, method or "")
    if refund > 0:
        create_refund_entry(
            locked, kind="customer", amount=refund, actor_name=actor_name,
            reason=f"訂單取消退款（已收 {received:,.0f}、沒收 {forfeited:,.0f}）",
            method_label=method_label, refunded_on=completed_on, reference=reference, item_name="取消退款",
        )
    now = timezone.now()
    locked.refund_amount = refund
    locked.forfeited_amount = forfeited
    locked.forfeit_reason = forfeit_reason[:250]
    locked.refund_completed_on = completed_on
    locked.refund_method = method if refund > 0 else ""
    locked.refund_reference = reference if refund > 0 else ""
    if proof is not None:
        locked.refund_proof = proof
    locked.cancellation_completed_at = now
    locked.cancellation_completed_by = actor_name
    locked.status = SalesOrder.Status.CANCELLED
    locked.save(update_fields=[
        "refund_amount", "forfeited_amount", "forfeit_reason", "refund_completed_on", "refund_method",
        "refund_reference", "refund_proof", "cancellation_completed_at", "cancellation_completed_by",
        "status", "updated_at",
    ])
    description = f"取消結算：已收 ${received:,.0f}、沒收 ${forfeited:,.0f}、退款 ${refund:,.0f}"
    if forfeited:
        description += f"（沒收原因：{locked.forfeit_reason}）"
    _audit(
        locked, actor_name=actor_name, reason="完成取消退款結算", event_type="refund_completed",
        changes={"取消結算": {"before": f"已收 {received:,.0f}", "after": f"沒收 {forfeited:,.0f}／退款 {refund:,.0f}"}},
        description=description + "；訂單完成取消",
    )
    from .notifications import notify
    notify("cancellation_settled", locked, f"訂單 {locked.number} 取消結算完成", description + "。")
    for name in ("refund_amount", "forfeited_amount", "forfeit_reason", "refund_completed_on", "refund_method",
                 "refund_reference", "refund_proof", "cancellation_completed_at", "cancellation_completed_by", "status"):
        setattr(order, name, getattr(locked, name))
    return locked


def settlement_gap(order, summary=None):
    """已交付的系統訂單在金額修正後產生的補收／退差；歷史匯入訂單不自動推算。"""
    from .payment_summary import payment_summary

    if not order.is_delivered or not order.cash_receivable_v2 or order.is_cancelled_sale:
        return None
    summary = summary or payment_summary(order)
    due = summary["customer_due"] if order.source_type != "dealer" else ZERO
    overpaid = summary["customer_overpaid"]
    if not due and not overpaid:
        return None
    return {"due": due, "overpaid": overpaid}
