from calendar import monthrange
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, F
from django.utils import timezone

from sales.models import (
    OrderDraft,
    OrderEvent,
    SalesOrder,
    VehicleInventory,
)
from sales.services.business_days import build_dealer_reminders
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


def _percent_change(current, previous):
    if previous == 0:
        return None
    return round(((current - previous) / abs(previous)) * 100, 1)


def _sales_snapshot(start, end, source=None):
    orders = list(
        SalesOrder.objects.filter(
            registration_date__gte=start,
            registration_date__lte=end,
        )
        .exclude(status__in=CANCELLED_STATUSES)
        .select_related("operations")
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
    source = list(SalesOrder.objects.filter(registration_date__range=(starts[0], today))
                  .exclude(status__in=CANCELLED_STATUSES).select_related('operations').prefetch_related('payment_records'))
    current = _sales_snapshot(month_start, today, source)
    previous = _sales_snapshot(previous_start, comparison_end, source)
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
    risk = {key: filter_payment_risk(all_orders, key).count() for key in ('outstanding', 'unconfirmed', 'refund')}

    active = SalesOrder.objects.exclude(
        status__in=[SalesOrder.Status.COMPLETED, SalesOrder.Status.CANCELLED]
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
    registration_fee_variances = list(
        SalesOrder.objects.filter(
            registration_date__isnull=False,
            registration_calculated_total__gt=0,
        )
        .exclude(status=SalesOrder.Status.CANCELLED)
        .exclude(plate_insurance_fee=F("registration_calculated_total"))
        .exclude(
            registration_fee_variance_confirmed_calculated_total=F(
                "registration_calculated_total"
            ),
            registration_fee_variance_confirmed_actual_total=F("plate_insurance_fee"),
        )
        .select_related("vehicle_model")
        .order_by("registration_date", "id")[:20]
    )
    return {
        'trend': trend,
        'charts': charts,
        'risk': risk,
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
                    SalesOrder.Status.TRANSFER_PENDING,
                    SalesOrder.Status.IN_TRANSFER,
                ]
            ).count(),
            "delivery": active.filter(
                status=SalesOrder.Status.DELIVERY_PENDING
            ).count(),
        },
        "inventory": {
            "total": VehicleInventory.objects.exclude(
                status=VehicleInventory.Status.INACTIVE
            ).count(),
            "available": inventory_counts.get(VehicleInventory.Status.AVAILABLE, 0),
            "reserved": inventory_counts.get(VehicleInventory.Status.RESERVED, 0),
            "transfer": (
                inventory_counts.get(VehicleInventory.Status.TRANSFER_PENDING, 0)
                + inventory_counts.get(VehicleInventory.Status.IN_TRANSFER, 0)
            ),
            "issues": inventory_counts.get(
                VehicleInventory.Status.CONDITION_ISSUE, 0
            ),
        },
        "urgent_statuses": urgent_statuses,
        "dealer_reminders": due_dealer_reminders,
        "registration_fee_variances": registration_fee_variances,
        "recent_orders": SalesOrder.objects.select_related(
            "vehicle_model", "color", "source"
        )
        .exclude(status=SalesOrder.Status.CANCELLED)
        .order_by("-created_at")[:5],
        "recent_events": OrderEvent.objects.select_related("order")
        .order_by("-created_at")[:5],
    }
