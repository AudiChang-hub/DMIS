"""首頁、總表的共用唯讀成交口徑；不變更底層財務快照。"""
from decimal import Decimal

from sales.models import PaymentRecord, SalesOrder

CANCELLED_STATUSES = (SalesOrder.Status.CANCELLED, SalesOrder.Status.CANCEL_REFUND_PENDING, SalesOrder.Status.EXCEPTION_CLOSED)


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
    if risk == 'refund':
        return orders.filter(status=SalesOrder.Status.CANCEL_REFUND_PENDING)
    if risk == 'outstanding':
        from .payment_summary import payment_summary
        candidates = orders.exclude(status__in=CANCELLED_STATUSES).select_related('legacy_snapshot').prefetch_related('payment_records', 'accessories')
        ids = []
        for order in candidates:
            summary = payment_summary(order)
            if summary['customer_due'] > 0 or summary['lender_due'] > 0 or not summary['legacy_settled']:
                ids.append(order.pk)
        return orders.exclude(status__in=CANCELLED_STATUSES).filter(pk__in=ids)
    if risk == 'unconfirmed':
        ids = PaymentRecord.objects.filter(received_amount__gt=0, confirmed=False).values('order_id')
        return orders.exclude(status__in=CANCELLED_STATUSES).filter(pk__in=ids)
    if risk == 'stale_allocation':
        from .order_next_actions import stale_allocation_since
        return orders.exclude(status__in=CANCELLED_STATUSES).filter(
            allocated_at__lt=stale_allocation_since(), allocated_vehicle__isnull=False,
            registration_completed_at__isnull=True, delivered_at__isnull=True,
        )
    if risk == 'overpaid':
        from .payment_summary import payment_summary
        candidates = orders.exclude(status__in=CANCELLED_STATUSES).filter(cash_receivable_v2=True).select_related('legacy_snapshot').prefetch_related('payment_records', 'accessories')
        ids = [order.pk for order in candidates
               if (summary := payment_summary(order))['customer_overpaid'] > 0 or summary['lender_overpaid'] > 0]
        return orders.exclude(status__in=CANCELLED_STATUSES).filter(pk__in=ids)
    return orders
