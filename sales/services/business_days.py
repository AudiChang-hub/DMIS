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


def registration_marks(today=None):
    """全部訂單「領牌日期」標色（T-255）：今天（台灣時區）與下一個工作日（跳過週末與營業日設定的假日）。"""
    today = today or timezone.localdate()
    return {"today": today, "next_business_day": add_business_days(today, 1)}


# 營運總表「車行尾款到期」的到期依據（T-280）：交車日的下一天起算工作日，到第 N 個工作天當天就算到期。
# 一定先領牌才交車（T-298），交車後領牌文件的提醒拿掉，只留尾款。
DEALER_BALANCE_DAYS = 7


def dealer_balance_owing(summary):
    """車行尾款還沒收清：只看客人（車行）要付的部分 customer_due，和「款項未結清」紅標、車行掛帳同一口徑；
    分期／平台撥款是事後對帳，跟車行無關（T-280，使用者 2026-11-21）。原本用 payment_confirmed，它連分期撥款
    未入帳也算未收清，車行分期單客人早已收清，卻因撥款未到一直被列成車行到期。"""
    return summary["customer_due"] > 0


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
            # Excel 匯入單＝歷史資料：尾款提醒不列（T-275 第 8 項，使用者 2026-11-21）。
            legacy_snapshot__isnull=True,
        )
        .exclude(status__in=[SalesOrder.Status.CANCELLED, SalesOrder.Status.EXCEPTION_CLOSED])
        # payment_summary 會讀 legacy_snapshot（匯入單判斷），一起帶出來，查詢數不隨張數增加（T-278 QA 疑慮 d）。
        .select_related("source", "operations", "vehicle_model", "legacy_snapshot")
        .prefetch_related("payment_records", "accessories")
    )
    from .payment_summary import payment_summary

    for order in orders:
        delivered_on = timezone.localtime(order.delivered_at).date()
        if dealer_balance_owing(payment_summary(order)):
            due = add_business_days(delivered_on, DEALER_BALANCE_DAYS, holidays)
            reminders.append(
                {
                    "order": order,
                    "kind": "dealer_balance",
                    "label": "車行尾款尚未確認",
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
