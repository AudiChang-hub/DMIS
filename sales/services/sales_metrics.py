"""首頁、總表的共用唯讀成交口徑；不變更底層財務快照。"""
from decimal import Decimal

from django.db.models import Q

from sales.models import PaymentRecord, SalesOrder

CANCELLED_STATUSES = (SalesOrder.Status.CANCELLED, SalesOrder.Status.CANCEL_REFUND_PENDING, SalesOrder.Status.EXCEPTION_CLOSED)
# 已交車的單不算配車保留逾期；交付時間可留空（T-138），不能只靠 delivered_at 判斷。
DELIVERED_STATUSES = (SalesOrder.Status.DELIVERED_DOCS_PENDING, SalesOrder.Status.COMPLETED)
# 營運總表款項依付款方式拆列（T-275 第 9 項，使用者 2026-11-21）：沿用既有欄位，不新增判斷資料。
PAYMENT_CATEGORIES = (("cash", "現金"), ("card", "刷卡"), ("installment", "分期"), ("platform", "平台"))
# 款項類的收款風險（T-275 第 8 項）：Excel 匯入單＝歷史資料，一律視為已收款、已對帳，這些篩選都不算匯入單。
MONEY_RISKS = ("outstanding", "unsettled_delivered", "unconfirmed", "refund", "overpaid", "before_delivery",
               "awaiting_payout")


def is_legacy_history(order):
    """Excel 匯入單（有 legacy_snapshot）＝歷史資料，統計與篩選一律視為已收款、已對帳（T-275 第 8 項，使用者
    2026-11-21）。只用在營運總表／首頁款項、全部訂單收款風險、款項未結清紅標、車行到期提醒；不改 payment_summary、
    統一撥款對帳、交車掛帳額度檢查與收款帳，也不寫資料。呼叫端要先 select_related("legacy_snapshot")。"""
    return hasattr(order, "legacy_snapshot")


def payment_category(order):
    """平台單一律算平台（撥款由平台付，和統一撥款對帳 channel 同一判斷）；其餘依 payment_type，其他算現金。"""
    if order.source_type == SalesOrder.SourceType.PLATFORM:
        return "platform"
    if order.payment_type in (SalesOrder.PaymentType.INSTALLMENT, SalesOrder.PaymentType.CARD):
        return order.payment_type
    return "cash"


def payment_category_q(key):
    """`payment_category` 的查詢版本；全部訂單 pay= 參數用。"""
    platform = Q(source_type=SalesOrder.SourceType.PLATFORM)
    if key == "platform":
        return platform
    if key in ("installment", "card"):
        return ~platform & Q(payment_type=key)
    return ~platform & ~Q(payment_type__in=("installment", "card"))


def is_outstanding(summary):
    """待收款：客人或分期／平台撥款還有應收，或收款未核（和 filter_payment_risk outstanding 同一口徑；匯入單由呼叫端先排除）。"""
    return summary['customer_due'] > 0 or summary['lender_due'] > 0 or not summary['legacy_settled']


def money_bucket(order, summary):
    """待收款的單在營運總表「錢」屬於哪一格：交車後未結清／已交車待撥款／交車前應收；不是待收回 None。"""
    if not is_outstanding(summary):
        return None
    if order.status in DELIVERED_STATUSES:
        # 和 order_list_unsettled.is_unsettled_after_delivery 同條件（已交車且客人應收未收清）。
        return "unsettled" if summary["customer_due"] > 0 else "awaiting_payout"
    return "before_delivery"


def vehicle_sale_amount(order):
    """車款成交額口徑：訂單車價；Excel 匯入的歷史訂單車價為 0 時，改用匯入時保存的收款價（不含強制險）。
    只用於報表彙總，不回寫訂單（使用者 2026-10-12 選定）。"""
    if order.vehicle_price:
        return order.vehicle_price
    snapshot = getattr(order, "legacy_snapshot", None)
    return snapshot.historical_received_price if snapshot and snapshot.historical_received_price else Decimal("0")


def summarize_sales(orders):
    summary = dict(count=0, vehicle_sales=Decimal('0'), actual_received=Decimal('0'),
                   net_profit=Decimal('0'), profit_ready=0)
    for order in orders:
        if order.is_cancelled_sale:
            continue
        profile = getattr(order, 'operations', None)
        summary['count'] += 1
        summary['vehicle_sales'] += vehicle_sale_amount(order)
        if profile:
            summary['actual_received'] += profile.total_received
            if profile.profit_is_ready:
                summary['profit_ready'] += 1
                summary['net_profit'] += profile.net_profit
    summary['average_price'] = summary['vehicle_sales'] / summary['count'] if summary['count'] else Decimal('0')
    summary['average_profit'] = summary['net_profit'] / summary['profit_ready'] if summary['profit_ready'] else None
    summary['profit_pending'] = summary['count'] - summary['profit_ready']
    return summary


def filter_payment_risk(orders, risk):
    if risk in MONEY_RISKS:
        orders = orders.filter(legacy_snapshot__isnull=True)   # 匯入單＝已收款已對帳（is_legacy_history）
    if risk == 'refund':
        return orders.filter(status=SalesOrder.Status.CANCEL_REFUND_PENDING)
    if risk == 'outstanding':
        from .payment_summary import payment_summary
        candidates = orders.exclude(status__in=CANCELLED_STATUSES).select_related('legacy_snapshot').prefetch_related('payment_records', 'accessories')
        ids = []
        for order in candidates:
            summary = payment_summary(order)
            if is_outstanding(summary):
                ids.append(order.pk)
        return orders.exclude(status__in=CANCELLED_STATUSES).filter(pk__in=ids)
    if risk in ('before_delivery', 'awaiting_payout'):
        # 營運總表「交車前應收」「已交車待撥款」（T-275 第 9 項）：和卡片共用 money_bucket。
        from .payment_summary import payment_summary
        candidates = orders.exclude(status__in=CANCELLED_STATUSES).select_related('legacy_snapshot').prefetch_related('payment_records', 'accessories')
        ids = [order.pk for order in candidates if money_bucket(order, payment_summary(order)) == risk]
        return orders.exclude(status__in=CANCELLED_STATUSES).filter(pk__in=ids)
    if risk == 'unsettled_delivered':
        # 營運總表「交車後未結清」（T-275）：條件與卡片共用 is_unsettled_after_delivery，比「待收款」窄。
        from .order_list_unsettled import is_unsettled_after_delivery
        from .payment_summary import payment_summary
        candidates = orders.filter(status__in=DELIVERED_STATUSES).select_related('legacy_snapshot').prefetch_related('payment_records', 'accessories')
        ids = [order.pk for order in candidates if is_unsettled_after_delivery(order, payment_summary(order))]
        return orders.filter(pk__in=ids)
    if risk == 'unconfirmed':
        ids = PaymentRecord.objects.filter(received_amount__gt=0, confirmed=False).values('order_id')
        return orders.exclude(status__in=CANCELLED_STATUSES).filter(pk__in=ids)
    if risk == 'stale_allocation':
        from .order_next_actions import stale_allocation_since
        return orders.exclude(status__in=CANCELLED_STATUSES).filter(
            allocated_at__lt=stale_allocation_since(), allocated_vehicle__isnull=False,
            registration_completed_at__isnull=True, delivered_at__isnull=True,
        ).exclude(status__in=DELIVERED_STATUSES)
    if risk == 'overpaid':
        from .payment_summary import payment_summary
        candidates = orders.exclude(status__in=CANCELLED_STATUSES).filter(cash_receivable_v2=True).select_related('legacy_snapshot').prefetch_related('payment_records', 'accessories')
        ids = [order.pk for order in candidates
               if (summary := payment_summary(order))['customer_overpaid'] > 0 or summary['lender_overpaid'] > 0]
        return orders.exclude(status__in=CANCELLED_STATUSES).filter(pk__in=ids)
    return orders
