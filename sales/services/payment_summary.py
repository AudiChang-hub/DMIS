"""應收與實收分離；自行新增的款項依明確分類加總，不猜測項目文字。"""
from decimal import Decimal

ZERO = Decimal("0")
EXPECTED_KEYS = {"deposit", "balance", "installment_disbursement"}


def payment_summary(order, records=None):
    from .customer_receivable import default_customer_balance
    from .operations_sync import _expected_installment_disbursement

    records = list(order.payment_records.all()) if records is None else list(records)
    keyed = {p.system_key: p for p in records if p.system_key}
    deposit = keyed["deposit"].expected_amount if "deposit" in keyed else (order.deposit_amount or ZERO)
    balance = keyed["balance"].expected_amount if "balance" in keyed else default_customer_balance(order)
    customer_expected = deposit + balance
    lender_expected = (keyed["installment_disbursement"].expected_amount if "installment_disbursement" in keyed
                       else _expected_installment_disbursement(order)) if order.payment_type == "installment" else ZERO
    totals = {"customer": ZERO, "lender": ZERO}
    for record in records:
        if record.confirmed:
            totals[record.effective_receipt_kind] += record.received_amount or ZERO
    # 舊有人工新增應收仍是額外義務，不能因介面簡化而消失。
    for record in records:
        if record.system_key not in EXPECTED_KEYS:
            if record.effective_receipt_kind == "lender":
                lender_expected += record.expected_amount or ZERO
            else:
                customer_expected += record.expected_amount or ZERO
    historical = order.status == "completed" and hasattr(order, "legacy_snapshot")
    if historical:
        # 已完成 Excel 訂單沒有當時完整價款快照，不憑現在欄位補出未曾存在的應收。
        customer_expected = sum((p.expected_amount for p in records if p.effective_receipt_kind == "customer"), ZERO)
        lender_expected = sum((p.expected_amount for p in records if p.effective_receipt_kind == "lender"), ZERO)
    customer_due = max(customer_expected - totals["customer"], ZERO)
    lender_due = max(lender_expected - totals["lender"], ZERO)
    delivery_due = customer_due
    if not order.cash_receivable_v2:
        # 舊流程的訂金欄已扣在尾款內，交付原本只核對尾款；不追加歷史阻擋條件。
        deposit_received = sum((p.received_amount for p in records if p.system_key == "deposit" and p.confirmed), ZERO)
        delivery_due = max(customer_expected - deposit - (totals["customer"] - deposit_received), ZERO)
    # 有既定應收的舊實收列仍須各自收清；新自由收款列的應收為零。
    legacy_settled = all(p.is_settled for p in records if (historical or p.system_key not in EXPECTED_KEYS) and p.expected_amount > 0)
    return dict(customer_expected=customer_expected, lender_expected=lender_expected,
                customer_received=totals["customer"], lender_received=totals["lender"],
                customer_due=customer_due, lender_due=lender_due,
                customer_settled=delivery_due <= 0, delivery_due=delivery_due,
                settled=bool(customer_expected + lender_expected > 0 and customer_due <= 0 and lender_due <= 0 and legacy_settled))


def disbursement_receipts(order, records=None):
    records = list(order.payment_records.all()) if records is None else records
    if order.payment_type == "installment":
        return [p for p in records if p.confirmed and p.effective_receipt_kind == "lender"]
    if order.source_type == "platform":
        return [p for p in records if p.confirmed and p.effective_receipt_kind == "customer" and p.system_key != "deposit"]
    return []
