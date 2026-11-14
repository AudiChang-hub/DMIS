from calendar import monthrange
from datetime import datetime, time, timedelta

from django.db.models import Count, prefetch_related_objects
from django.utils import timezone

from sales.models import (
    OrderDraft,
    SalesOrder,
    registration_confirmed_q,
    VehicleInventory,
)
from sales.services.business_days import build_dealer_reminders
from sales.services.payment_summary import payment_summary
from sales.services.sales_metrics import CANCELLED_STATUSES, filter_payment_risk, summarize_sales


def _month_bounds(day):
    start = day.replace(day=1)
    end = day.replace(day=monthrange(day.year, day.month)[1])
    return start, end


def _previous_month(day):
    return (day.replace(day=1) - timedelta(days=1)).replace(day=1)


def _aware_start(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def _aware_end(day):
    return timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min))


def _last_year(day):
    """去年同一天；2/29 對到 2/28。"""
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return day.replace(year=day.year - 1, day=28)


# 在庫＝還在店裡的車：可售、已預留、車況異常（T-167；已售出、調出、已交車、停用都不算）。
ON_HAND_STATUSES = (
    VehicleInventory.Status.AVAILABLE,
    VehicleInventory.Status.RESERVED,
    VehicleInventory.Status.CONDITION_ISSUE,
)


def _percent_change(current, previous):
    if previous == 0:
        return None
    return round(((current - previous) / abs(previous)) * 100, 1)


def _sales_snapshot(start, end, source=None):
    orders = list(
        # 只算按過「確認完成」的領牌日；確認前填的是預計日（T-172 A′）。
        SalesOrder.objects.filter(
            registration_confirmed_q(),
            registration_date__gte=start,
            registration_date__lte=end,
        )
        .exclude(status__in=CANCELLED_STATUSES)
        .select_related("operations", "legacy_snapshot")
        .prefetch_related("payment_records")
    ) if source is None else [order for order in source if start <= order.registration_date <= end]
    summary = summarize_sales(orders)
    return {
        **summary,
        "orders": orders,
        "sales_total": summary['vehicle_sales'],
        "profit_total": summary['net_profit'],
    }


def build_dashboard_metrics(today=None):
    today = today or timezone.localdate()
    month_start, month_end = _month_bounds(today)
    previous_start, previous_end = _month_bounds(_previous_month(today))
    comparison_end = previous_end if today == month_end else previous_start.replace(day=min(today.day, previous_end.day))
    starts = [month_start]
    for _ in range(11):
        starts.insert(0, _previous_month(starts[0]))
    # 往前多取 12 個月當去年同期對照（T-167）；既有 12 個月走勢的口徑不變。
    last_year_today = _last_year(today)
    last_year_starts = [start.replace(year=start.year - 1) for start in starts]
    # T-170 效能：未取消的單只載入一次，同時供「未結清／溢收」判斷與 24 個月成交彙總使用；
    # 收款紀錄要用 prefetch（OrderOperationsProfile.total_received 讀預載快取，否則逐張查）；配件、其他費用
    # payment_summary 用不到，不預載。營運資料與車型只補抓 24 個月內那幾張（不對全部單 join）。
    # 結果和原本逐項查詢相同（test_operations_cockpit 有對照）。
    open_orders = list(SalesOrder.objects.exclude(status__in=CANCELLED_STATUSES).select_related('legacy_snapshot')
                       .prefetch_related('payment_records'))
    source = [order for order in open_orders
              if order.confirmed_registration_date and last_year_starts[0] <= order.registration_date <= today]
    prefetch_related_objects(source, 'operations', 'vehicle_model')
    summaries = {order.pk: payment_summary(order) for order in open_orders}
    current = _sales_snapshot(month_start, today, source)
    previous = _sales_snapshot(previous_start, comparison_end, source)
    trend_last_year = []
    for start in last_year_starts:
        end = min(_month_bounds(start)[1], last_year_today)
        trend_last_year.append({'label': start.strftime('%Y/%m'), 'start': start.isoformat(), 'end': end.isoformat(),
                                **_sales_snapshot(start, end, source)})
    trend = []
    for start in starts:
        end = min(_month_bounds(start)[1], today)
        trend.append({'label': start.strftime('%Y/%m'), 'start': start.isoformat(), 'end': end.isoformat(),
                      **_sales_snapshot(start, end, source)})
    charts = []
    for key, label, unit in [('count', '領牌成交台數', '台'), ('sales_total', '車款成交額', '元'), ('profit_total', '可計入訂單淨利', '元')]:
        values = [float(row[key]) if key != 'profit_total' or row['profit_ready'] else None for row in trend]
        low, high = min([0] + [v for v in values if v is not None]), max([0] + [v for v in values if v is not None])
        scale = high - low or 1
        zero_y = 130 - (0 - low) / scale * 110
        points, segments, segment = [], [], []
        for index, (row, value) in enumerate(zip(trend, values)):
            if value is None:
                if segment:
                    segments.append(' '.join(segment))
                    segment = []
                continue
            x, y = 20 + index * 40, 130 - (value - low) / scale * 110
            segment.append(f'{x},{y:.2f}')
            points.append({'x': x, 'y': f'{y:.2f}', 'label': row['label'], 'value': row[key]})
        if segment:
            segments.append(' '.join(segment))
        charts.append({'label': label, 'unit': unit, 'segments': segments, 'points': points,
                       'low': low, 'high': high, 'zero_y': f'{zero_y:.2f}'})
    all_orders = SalesOrder.objects.all()
    # 未結清與溢收：條件和 filter_payment_risk 同一套，只是用上面已算好的 payment_summary，不再各自重載全部訂單。
    outstanding = [order for order in open_orders
                   if (summary := summaries[order.pk])['customer_due'] > 0 or summary['lender_due'] > 0
                   or not summary['legacy_settled']]
    outstanding_ids = [order.pk for order in outstanding]
    overpaid_ids = [order.pk for order in open_orders if order.cash_receivable_v2
                    and ((summary := summaries[order.pk])['customer_overpaid'] > 0 or summary['lender_overpaid'] > 0)]
    open_queryset = all_orders.exclude(status__in=CANCELLED_STATUSES)
    risk_orders = {
        'outstanding': open_queryset.filter(pk__in=outstanding_ids),
        'unconfirmed': filter_payment_risk(all_orders, 'unconfirmed'),
        'refund': filter_payment_risk(all_orders, 'refund'),
        'overpaid': open_queryset.filter(pk__in=overpaid_ids),
        'stale_allocation': filter_payment_risk(all_orders, 'stale_allocation'),
    }
    precounted = {'outstanding': len(outstanding_ids), 'overpaid': len(overpaid_ids)}
    risk = {key: precounted[key] if key in precounted else rows.count() for key, rows in risk_orders.items()}

    active = SalesOrder.objects.exclude(
        status__in=[SalesOrder.Status.COMPLETED, SalesOrder.Status.CANCELLED, SalesOrder.Status.EXCEPTION_CLOSED]
    )
    urgent_statuses = [
        SalesOrder.Status.CANCEL_REFUND_PENDING,
        SalesOrder.Status.DELIVERED_DOCS_PENDING,
    ]
    dealer_reminders = build_dealer_reminders(today)
    due_dealer_reminders = [item for item in dealer_reminders if item["is_due"]]
    in_progress = active.exclude(
        status__in=[SalesOrder.Status.ALLOCATION_PENDING, *urgent_statuses]
    )
    inventory_counts = dict(
        VehicleInventory.objects.values_list("status")
        .annotate(total=Count("id"))
        .values_list("status", "total")
    )
    from .order_filters import fee_variance_orders
    registration_fee_variances = fee_variance_orders(SalesOrder.objects.all()).order_by("registration_date", "id")
    return {
        'trend': trend,
        'trend_last_year': trend_last_year,
        'charts': charts,
        'risk': risk,
        'risk_orders': risk_orders,
        # 未結清的單與其 payment_summary（已載入的物件，營運總表「錢」直接用，不再重查）。
        'outstanding_summaries': [(order, summaries[order.pk]) for order in outstanding],
        'new_orders': all_orders.filter(established_on__range=(month_start, today)).exclude(status__in=CANCELLED_STATUSES).count(),
        "period": {
            "label": f"{month_start.year}年{month_start.month}月",
            "start": month_start,
            "end": today,
            "previous_start": previous_start,
            "previous_end": comparison_end,
        },
        "performance": {
            **current,
            "count_change": _percent_change(current["count"], previous["count"]),
            "sales_change": _percent_change(
                current["sales_total"], previous["sales_total"]
            ),
            "profit_change": _percent_change(
                current["profit_total"], previous["profit_total"]
            ),
        },
        "workload": {
            "drafts": OrderDraft.objects.count(),
            "urgent": active.filter(status__in=urgent_statuses).count(),
            "allocation": active.filter(
                status=SalesOrder.Status.ALLOCATION_PENDING
            ).count(),
            "in_progress": in_progress.count(),
            "registration": active.filter(
                status__in=[
                    SalesOrder.Status.ALLOCATED,
                ]
            ).count(),
            "delivery": active.filter(
                status=SalesOrder.Status.DELIVERY_PENDING
            ).count(),
        },
        "inventory": {
            "total": sum(inventory_counts.get(status, 0) for status in ON_HAND_STATUSES),
            "available": inventory_counts.get(VehicleInventory.Status.AVAILABLE, 0),
            "reserved": inventory_counts.get(VehicleInventory.Status.RESERVED, 0),
            "issues": inventory_counts.get(
                VehicleInventory.Status.CONDITION_ISSUE, 0
            ),
        },
        "urgent_statuses": urgent_statuses,
        "dealer_reminders": due_dealer_reminders,
        "registration_fee_variances": registration_fee_variances,
    }
