"""首頁、總表的共用唯讀成交口徑；不變更底層財務快照。"""
from decimal import Decimal

from django.db.models import Q

from sales.models import PaymentRecord, SalesOrder

ZERO = Decimal("0")
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
    統一撥款對帳、車行未付（交車時記錄）與收款帳，也不寫資料。呼叫端要先 select_related("legacy_snapshot")。"""
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


def platform_payout_estimate(order):
    """平台撥款待入帳的預估金額（T-278 B1-A，使用者 2026-11-21）；不是平台待撥款回 None。

    平台撥款列應收是 0（T-96，平台不先給預計金額），payment_summary 算不出撥款應收，所以另外判斷：非匯入、
    未取消的平台單，只要「平台撥款」列還沒入帳就算待收，金額取收支的預估車價收入（actual_disbursement，
    入帳前就是預估）。只給營運總表／首頁待收與全部訂單收款風險用；payment_summary、交車閘門、「款項未結清」
    紅標都不看它（平台撥款是事後對帳，不能擋交車）。呼叫端要先預載 payment_records，operations 只在待撥款時才讀。"""
    if order.source_type != SalesOrder.SourceType.PLATFORM or order.status in CANCELLED_STATUSES or is_legacy_history(order):
        return None
    if not any(p.system_key == "platform_disbursement" and not p.confirmed
               and p.entry_type == PaymentRecord.EntryType.RECEIPT for p in order.payment_records.all()):
        return None
    profile = getattr(order, "operations", None)
    return max(profile.actual_disbursement or ZERO, ZERO) if profile else ZERO


def money_summary(order, summary):
    """payment_summary 再加上平台撥款預估（platform_due，None＝沒有）；營運總表「錢」與收款風險共用。"""
    return {**summary, "platform_due": platform_payout_estimate(order)}


def is_outstanding(summary):
    """待收款：客人或分期撥款還有應收、收款未核，或平台撥款未入帳（summary 用 money_summary；和 filter_payment_risk
    outstanding 同一口徑；匯入單由呼叫端先排除）。"""
    return (summary['customer_due'] > 0 or summary['lender_due'] > 0 or not summary['legacy_settled']
            or summary.get('platform_due') is not None)


def payout_due(summary):
    """待收裡分期／平台撥款的部分（平台是預估）。"""
    return max(summary['lender_due'], ZERO) + (summary.get('platform_due') or ZERO)


def money_bucket(order, summary):
    """待收款的單在營運總表「錢」屬於哪一格：交車後未結清／已交車待撥款／未交車・尾款待收；不是待收回 None。"""
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
        candidates = orders.exclude(status__in=CANCELLED_STATUSES).select_related('legacy_snapshot', 'operations').prefetch_related('payment_records', 'accessories')
        ids = []
        for order in candidates:
            summary = money_summary(order, payment_summary(order))
            if is_outstanding(summary):
                ids.append(order.pk)
        return orders.exclude(status__in=CANCELLED_STATUSES).filter(pk__in=ids)
    if risk in ('before_delivery', 'awaiting_payout'):
        # 營運總表「未交車・尾款待收」「已交車待撥款」（T-275 第 9 項）：和卡片共用 money_bucket。
        from .payment_summary import payment_summary
        candidates = orders.exclude(status__in=CANCELLED_STATUSES).select_related('legacy_snapshot', 'operations').prefetch_related('payment_records', 'accessories')
        ids = [order.pk for order in candidates if money_bucket(order, money_summary(order, payment_summary(order))) == risk]
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
