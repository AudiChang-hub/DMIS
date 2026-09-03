"""唯讀一致性檢查；不以現行費率修補歷史金額。"""
from collections import Counter
from decimal import Decimal

from sales.models import DealerVolumeBonusSettlement, SalesOrder


def audit_financial_consistency(sample_limit=30):
    counts = Counter()
    samples = []

    def report(code, order, detail):
        counts[code] += 1
        if len(samples) < sample_limit:
            samples.append({"code": code, "order": order.number, "detail": detail})

    total = 0
    orders = SalesOrder.objects.select_related("operations", "vehicle_model", "source").prefetch_related(
        "payment_records", "accessories", "other_fees", "dealer_volume_bonus_allocations",
    ).order_by("pk")
    for order in orders.iterator(chunk_size=200):
        total += 1
        profile = getattr(order, "operations", None)
        if not profile:
            report("missing_operations", order, "缺少營運資料")
            continue
        protected = set(profile.manual_financial_fields or [])
        payments = list(order.payment_records.all())
        calculated = order.calculate_balance()
        if order.calculated_balance != calculated:
            report("balance_formula_mismatch", order, f"保存 {order.calculated_balance}／公式 {calculated}")
        if order.actual_balance != order.calculated_balance and not order.balance_adjustment_reason:
            report("balance_reason_missing", order, "人工尾款與計算值不同但缺原因")
        confirmed = bool(payments and sum(p.expected_amount for p in payments) > 0
                         and all(p.is_settled for p in payments))
        if profile.payment_confirmed != confirmed:
            report("payment_confirmation_mismatch", order, "收清狀態不符逐筆收款")
        for field, value in (("card_fee_income", sum(p.card_fee_charged for p in payments)),
                             ("card_fee_expense", sum(p.bank_card_fee for p in payments))):
            if getattr(profile, field) != value:
                report("card_fee_mismatch", order, f"{field}：保存 {getattr(profile, field)}／收款 {value}")
        key = ("installment_disbursement" if order.payment_type == "installment"
               else "balance" if order.source_type == "platform" else None)
        primary = next((p for p in payments if p.system_key == key and p.confirmed), None) if key else None
        if primary and profile.actual_disbursement != primary.received_amount:
            report("confirmed_disbursement_mismatch", order, "已確認撥款與營運實際撥款不同，需核對人工覆寫")
        if primary and not profile.payment_disbursement_snapshot:
            report("legacy_disbursement_no_snapshot", order, "舊確認資料無撤回快照，不自動推測原值")
        if order.registration_completed_at and not profile.vehicle_cost:
            report("registered_cost_missing", order, "已領牌但成本為零，淨利尚待核對")
        allocations = list(order.dealer_volume_bonus_allocations.all())
        if profile.dealer_commission_locked_at and "dealer_commission_expense" not in protected:
            expected = profile.dealer_commission_base + profile.dealer_commission_adjustment + sum(a.amount for a in allocations)
            if profile.dealer_commission_expense != expected:
                report("commission_total_mismatch", order, f"保存 {profile.dealer_commission_expense}／快照加獎金 {expected}")
        if allocations and "dealer_commission_expense" in protected:
            report("manual_commission_needs_review", order, "人工總額包含獎金與否不明，需核對")
        if order.status == "cancelled" and any(p.confirmed and p.received_amount for p in payments):
            report("cancelled_receipts_need_review", order, "取消／退款與收款分開留存，需以退款紀錄核對淨現金")
    for settlement in DealerVolumeBonusSettlement.objects.prefetch_related("allocations__order").order_by("pk"):
        allocations = list(settlement.allocations.all())
        if sum((a.amount for a in allocations), Decimal("0")) != settlement.actual_amount or len(allocations) != settlement.qualified_quantity:
            counts["settlement_allocation_mismatch"] += 1
            if len(samples) < sample_limit:
                samples.append({"code": "settlement_allocation_mismatch", "settlement": settlement.pk,
                                "detail": "結算金額或台數與分攤明細不同"})
    return {"orders_scanned": total, "finding_counts": dict(sorted(counts.items())), "samples": samples,
            "read_only": True, "note": "發現項目包含需人工確認的歷史差異，不代表全部為程式錯帳；未修改金額。"}
