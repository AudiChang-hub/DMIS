"""車行未付：未收清先交車的累計追蹤（只追蹤，不擋交車；車行額度 2026-11-23 T-288 移除）。"""
from decimal import Decimal

ZERO = Decimal("0")
ON_ACCOUNT_STATUSES = ("delivered_docs_pending", "completed")


def on_account_orders(dealer_id, exclude_order_id=None):
    """已交車且仍有客戶應收的系統訂單；歷史匯入應收依據不完整，不列入。"""
    from sales.models import SalesOrder
    from .payment_summary import payment_summary

    orders = SalesOrder.objects.filter(
        source_type=SalesOrder.SourceType.DEALER, source_id=dealer_id,
        status__in=ON_ACCOUNT_STATUSES, cash_receivable_v2=True,
    ).prefetch_related("payment_records", "accessories", "other_fees")
    if exclude_order_id:
        orders = orders.exclude(pk=exclude_order_id)
    result = []
    for order in orders:
        due = payment_summary(order)["customer_due"]
        if due > 0:
            result.append((order, due))
    return result


def dealer_outstanding(dealer_id, exclude_order_id=None):
    return sum((due for _order, due in on_account_orders(dealer_id, exclude_order_id)), ZERO)


def credit_overview(order, summary):
    """交付頁顯示用：本單待收、車行其他已交車未收清。"""
    if order.source_type != "dealer" or not order.source_id:
        return None
    return {
        "due": summary["customer_due"],
        "outstanding": dealer_outstanding(order.source_id, exclude_order_id=order.pk),
    }
