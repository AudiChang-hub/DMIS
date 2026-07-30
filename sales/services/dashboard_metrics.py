from calendar import monthrange
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count
from django.utils import timezone

from sales.models import (
    OrderDraft,
    OrderEvent,
    SalesOrder,
    VehicleInventory,
)


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
        return None if current == 0 else 100
    return round(((current - previous) / previous) * 100, 1)


def _sales_snapshot(start, end):
    orders = list(
        SalesOrder.objects.filter(
            delivered_at__gte=_aware_start(start),
            delivered_at__lt=_aware_end(end),
        )
        .exclude(status=SalesOrder.Status.CANCELLED)
        .select_related("operations")
    )
    sales_total = sum(
        (order.actual_balance + order.deposit_amount for order in orders),
        Decimal("0"),
    )
    profit_total = Decimal("0")
    profit_ready = 0
    for order in orders:
        profile = getattr(order, "operations", None)
        if profile and profile.vehicle_cost:
            profit_total += profile.net_profit
            profit_ready += 1
    return {
        "orders": orders,
        "count": len(orders),
        "sales_total": sales_total,
        "profit_total": profit_total,
        "profit_ready": profit_ready,
        "average_profit": (
            profit_total / profit_ready if profit_ready else Decimal("0")
        ),
    }


def build_dashboard_metrics(today=None):
    today = today or timezone.localdate()
    month_start, month_end = _month_bounds(today)
    previous_start, previous_end = _month_bounds(_previous_month(today))
    current = _sales_snapshot(month_start, month_end)
    previous = _sales_snapshot(previous_start, previous_end)

    active = SalesOrder.objects.exclude(
        status__in=[SalesOrder.Status.COMPLETED, SalesOrder.Status.CANCELLED]
    )
    urgent_statuses = [
        SalesOrder.Status.CANCEL_REFUND_PENDING,
        SalesOrder.Status.DELIVERED_DOCS_PENDING,
    ]
    in_progress = active.exclude(
        status__in=[SalesOrder.Status.ALLOCATION_PENDING, *urgent_statuses]
    )
    inventory_counts = dict(
        VehicleInventory.objects.values_list("status")
        .annotate(total=Count("id"))
        .values_list("status", "total")
    )
    return {
        "period": {
            "label": f"{month_start.year}年{month_start.month}月",
            "start": month_start,
            "end": month_end,
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
        "recent_orders": SalesOrder.objects.select_related(
            "vehicle_model", "color", "source"
        )
        .exclude(status=SalesOrder.Status.CANCELLED)
        .order_by("-created_at")[:5],
        "recent_events": OrderEvent.objects.select_related("order")
        .order_by("-created_at")[:5],
    }
