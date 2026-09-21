"""首頁、總表的共用唯讀成交口徑；不變更底層財務快照。"""
from decimal import Decimal

from sales.models import PaymentRecord, SalesOrder

CANCELLED_STATUSES = (SalesOrder.Status.CANCELLED, SalesOrder.Status.CANCEL_REFUND_PENDING)


def summarize_sales(orders):
    summary = dict(count=0, vehicle_sales=Decimal('0'), actual_received=Decimal('0'),
                   net_profit=Decimal('0'), profit_ready=0)
    for order in orders:
        if order.is_cancelled_sale:
            continue
        profile = getattr(order, 'operations', None)
        summary['count'] += 1
        summary['vehicle_sales'] += order.vehicle_price
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
    return orders
