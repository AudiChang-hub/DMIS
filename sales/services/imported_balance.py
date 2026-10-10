"""Excel 匯入、尚未完成的訂單：總應付與尾款（使用者 2026-10-10 選方案 C）。

匯入訂單的車價存為 0，成交價保留在匯入快照：
- 總應付＝Excel「收款價」（不含強制險）＋「強制險收入」；尾款＝總應付－已確認的客戶收款。
- 「車行收款」打 V＝已收清：尾款視為 0，不補任何收款紀錄。
- 沒打 V：以總應付作為客戶應收，交車前要收清（與新訂單相同），車行單照車行掛帳計算。
已完成、取消與結案的歷史訂單，以及分期單不套用。
"""
from decimal import Decimal

from sales.services.legacy_finance import source_decimal

PAID_MARKS = {"V", "Ｖ", "✓", "✔", "ˇ"}
OPEN_STATUSES = {
    "draft", "intake_pending", "allocation_pending", "allocated",
    "delivery_pending", "delivered_docs_pending",
}


def imported_due(order):
    """回傳 dict（price、insurance、total、paid_in_excel），不適用時回傳 None。"""
    # 系統新口徑訂單一定不是匯入單：先排除，避免列表逐筆查詢匯入快照。
    if order.cash_receivable_v2 or order.status not in OPEN_STATUSES or not hasattr(order, "legacy_snapshot"):
        return None
    if order.payment_type != "cash":
        # 分期單的收款價含分期公司撥款，不能全數算成客人尾款；維持原算法。
        return None
    snapshot = order.legacy_snapshot
    raw = snapshot.raw_financials or {}
    price = Decimal(snapshot.historical_received_price or 0)
    try:
        insurance = source_decimal(raw.get("強制險收入")).quantize(Decimal("1"))
    except ValueError:
        insurance = Decimal("0")
    mark = str(raw.get("車行收款") or "").strip().upper()
    return {
        "price": price,
        "insurance": insurance,
        "total": price + insurance,
        "paid_in_excel": mark in PAID_MARKS,
    }
