"""應收與實收分離；自行新增的款項依明確分類加總，不猜測項目文字。"""
from decimal import Decimal

ZERO = Decimal("0")
EXPECTED_KEYS = {"deposit", "balance", "installment_disbursement", "platform_disbursement"}


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
    # 未完成的 Excel 匯入訂單：沒打「車行收款」V 時，以 Excel 收款價＋強制險收入作為客戶應收（方案 C）。
    from .imported_balance import imported_due
    imported = imported_due(order)
    imported_open = bool(imported and not imported["paid_in_excel"])
    if imported and imported["paid_in_excel"]:
        # 「車行收款」打 V＝已收清：應收以已收為準（尾款 0），不補收款紀錄。
        customer_expected = totals["customer"]
    if imported_open:
        # 匯入時建立的「歷史收款」列（legacy_cash／legacy_card）是實收，不是額外應收。
        extra = sum((p.expected_amount or ZERO for p in records
                     if p.system_key not in EXPECTED_KEYS and not p.system_key.startswith("legacy_")
                     and p.effective_receipt_kind == "customer"), ZERO)
        customer_expected = imported["total"] + extra
    if historical:
        # 已完成 Excel 訂單沒有當時完整價款快照，不憑現在欄位補出未曾存在的應收。
        customer_expected = sum((p.expected_amount for p in records if p.effective_receipt_kind == "customer"), ZERO)
        lender_expected = sum((p.expected_amount for p in records if p.effective_receipt_kind == "lender"), ZERO)
    customer_due = max(customer_expected - totals["customer"], ZERO)
    lender_due = max(lender_expected - totals["lender"], ZERO)
    delivery_due = customer_due
    if not order.cash_receivable_v2 and not imported:
        # 舊流程的訂金欄已扣在尾款內，交付原本只核對尾款；不追加歷史阻擋條件。
        deposit_received = sum((p.received_amount for p in records if p.system_key == "deposit" and p.confirmed), ZERO)
        delivery_due = max(customer_expected - deposit - (totals["customer"] - deposit_received), ZERO)
    # 有既定應收的舊實收列仍須各自收清；新自由收款列的應收為零。
    legacy_settled = all(p.is_settled for p in records if (historical or p.system_key not in EXPECTED_KEYS) and p.expected_amount > 0)
    # 溢收只在系統建立的新口徑訂單推算；舊資料應收依據不完整，不自動判定多收。
    overpay_known = order.cash_receivable_v2 and not historical
    customer_overpaid = max(totals["customer"] - customer_expected, ZERO) if overpay_known else ZERO
    lender_overpaid = max(totals["lender"] - lender_expected, ZERO) if overpay_known and order.payment_type == "installment" else ZERO
    unconfirmed = sum((p.received_amount for p in records if not p.confirmed and p.received_amount > 0), ZERO)
    return dict(customer_expected=customer_expected, lender_expected=lender_expected,
                customer_received=totals["customer"], lender_received=totals["lender"],
                customer_due=customer_due, lender_due=lender_due,
                customer_overpaid=customer_overpaid, lender_overpaid=lender_overpaid,
                unconfirmed_received=unconfirmed,
                customer_settled=delivery_due <= 0, delivery_due=delivery_due,
                legacy_settled=legacy_settled,
                settled=bool(customer_expected + lender_expected > 0 and customer_due <= 0 and lender_due <= 0 and legacy_settled))


def balance_breakdown(order, summary=None, records=None):
    """交車收尾款的應收對帳單（使用者 2026-10-22 T-73、T-76）。

    從組成項目開始：車價、配件、牌險、選號、其他費用…加總＝費用合計，扣已核准優惠＝總價，
    再扣舊車折抵、分期公司撥款、已收訂金、其他已收款＝應收。應收一律取 payment_summary 的 delivery_due
    （與交車判斷同一個數字）；逐項推算對不上（人工調整過的尾款、舊資料）時改列收支合計並標示 fallback，不另算一套。
    0 元的項目不列。"""
    records = list(order.payment_records.all()) if records is None else list(records)
    summary = summary or payment_summary(order, records)
    due = summary["delivery_due"]
    customer = [p for p in records if p.effective_receipt_kind != "lender"]
    extras = sum((p.expected_amount or ZERO for p in customer if p.system_key not in EXPECTED_KEYS), ZERO)
    base = summary["customer_expected"] - extras  # 訂金＋尾款的應收
    deposit_received = sum((p.received_amount or ZERO for p in customer if p.system_key == "deposit" and p.confirmed), ZERO)
    other_received = summary["customer_received"] - deposit_received

    accessories = [(f"{line.name}{f' ×{line.quantity}' if line.quantity != 1 else ''}", line.line_total)
                   for line in order.accessories.all() if line.line_total]
    fees = [(fee.name or "其他費用", fee.amount) for fee in order.other_fees.all() if fee.amount]
    charges = [
        {"label": "車價", "amount": order.vehicle_price or ZERO, "items": []},
        {"label": "配件", "amount": order.accessory_total or ZERO, "items": accessories},
        {"label": "牌險費", "amount": order.plate_insurance_fee or ZERO, "items": []},
        {"label": "選號費", "amount": order.plate_selection_fee or ZERO, "items": []},
        {"label": "動保設定費", "amount": order.lien_registration_fee or ZERO, "items": []},
        {"label": "分期開辦費", "amount": order.effective_installment_fee or ZERO, "items": []},
        {"label": "其他費用", "amount": order.other_fee_total or ZERO, "items": fees},
        {"label": "舊車稅", "amount": order.old_vehicle_tax or ZERO, "items": []},
    ]
    charges = [row for row in charges if row["amount"]]
    charges_total = sum((row["amount"] for row in charges), ZERO)
    discount = order.approved_discount_amount or ZERO
    total = charges_total - discount
    valuation = order.old_vehicle_valuation or ZERO
    lender = total - valuation - base
    deductions = []
    if valuation:
        deductions.append({"label": "舊車折抵", "amount": valuation})
    if order.payment_type == "installment" and lender > 0:
        deductions.append({"label": "分期公司撥款（車價分期）", "amount": lender})
        lender = ZERO
    if deposit_received:
        deductions.append({"label": "已收訂金", "amount": deposit_received})
    if other_received:
        deductions.append({"label": "其他已收款", "amount": other_received})
    computed = total + extras - sum((row["amount"] for row in deductions), ZERO)
    exact = lender == ZERO and charges_total == order.pre_discount_total and max(computed, ZERO) == due
    lines = ([(row["label"], row["amount"], "+") for row in charges]
             + ([("已核准優惠", discount, "-")] if discount else [])
             + ([("其他應收", extras, "+")] if extras else [])
             + [(row["label"], row["amount"], "-") for row in deductions])
    fallback = []
    if not exact:
        fallback = [{"label": "客戶應收合計", "amount": summary["customer_expected"], "sign": "+"},
                    {"label": "已收款", "amount": summary["customer_received"], "sign": "-"}]
    return {
        "due": due, "exact": exact, "charges": charges, "charges_total": charges_total, "discount": discount,
        "total": total, "extras": extras, "deductions": deductions, "lines": lines if exact else [], "fallback": fallback,
        "received": summary["customer_received"],
    }


def effective_records(records):
    """排除已被沖銷的收款與其沖銷列（兩者淨額為零）；退款列保留為實際退回。"""
    records = list(records)
    reversed_ids = {p.reverses_id for p in records if p.entry_type == "reversal" and p.reverses_id}
    return [p for p in records if p.entry_type != "reversal" and p.pk not in reversed_ids]


def disbursement_receipts(order, records=None):
    records = effective_records(order.payment_records.all() if records is None else records)
    if order.payment_type == "installment":
        return [p for p in records if p.confirmed and p.effective_receipt_kind == "lender"]
    if order.source_type == "platform":
        if hasattr(order, "legacy_snapshot"):
            # Excel 匯入的平台單以「歷史收款」同步過實際車價收入，維持舊規則，不還原既有金額。
            return [p for p in records if p.confirmed and p.effective_receipt_kind == "customer" and p.system_key != "deposit"]
        # 平台撥款只認對帳頁入帳的平台撥款列；客人另付的牌險等款項不是平台撥款（T-96）。
        return [p for p in records if p.confirmed and p.effective_receipt_kind == "lender"]
    return []
