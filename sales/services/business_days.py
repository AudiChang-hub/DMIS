from datetime import timedelta

from django.utils import timezone

from sales.models import BusinessHoliday, SalesOrder


def is_business_day(day, holiday_dates=None):
    if day.weekday() >= 5:
        return False
    if holiday_dates is None:
        holiday_dates = set(
            BusinessHoliday.objects.filter(active=True).values_list("date", flat=True)
        )
    return day not in holiday_dates


def add_business_days(start, days, holiday_dates=None):
    """從實際交付日的下一天開始計算指定工作日數。"""
    if days < 0:
        raise ValueError("工作日數不可小於零")
    holiday_dates = holiday_dates if holiday_dates is not None else set(
        BusinessHoliday.objects.filter(active=True).values_list("date", flat=True)
    )
    current = start
    counted = 0
    while counted < days:
        current += timedelta(days=1)
        if is_business_day(current, holiday_dates):
            counted += 1
    return current


def build_dealer_reminders(today=None):
    today = today or timezone.localdate()
    holidays = set(
        BusinessHoliday.objects.filter(active=True).values_list("date", flat=True)
    )
    reminders = []
    orders = (
        SalesOrder.objects.filter(
            source_type=SalesOrder.SourceType.DEALER,
            delivered_at__isnull=False,
        )
        .exclude(status=SalesOrder.Status.CANCELLED)
        .select_related("source", "operations", "vehicle_model")
    )
    for order in orders:
        delivered_on = timezone.localtime(order.delivered_at).date()
        if not order.is_registration_complete:
            due = add_business_days(delivered_on, 3, holidays)
            reminders.append(
                {
                    "order": order,
                    "kind": "registration_documents",
                    "label": "交車後領牌文件未完成",
                    "due_date": due,
                    "days_overdue": max((today - due).days, 0),
                    "is_overdue": today > due,
                    "is_due": today >= due,
                }
            )
        profile = getattr(order, "operations", None)
        if not profile or not profile.payment_confirmed:
            due = add_business_days(delivered_on, 7, holidays)
            reminders.append(
                {
                    "order": order,
                    "kind": "dealer_balance",
                    "label": "合作車行尾款尚未確認",
                    "due_date": due,
                    "days_overdue": max((today - due).days, 0),
                    "is_overdue": today > due,
                    "is_due": today >= due,
                }
            )
    return sorted(
        reminders,
        key=lambda item: (
            not item["is_overdue"],
            not item["is_due"],
            item["due_date"],
            item["order"].id,
        ),
    )
