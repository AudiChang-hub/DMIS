from calendar import monthrange
from datetime import date


def bonus_period_dates(period_type, year, period):
    """以國曆月份／季度計算含首尾日的範圍，不依瀏覽器日期決定結算期間。"""
    if period_type not in {"month", "quarter"}:
        raise ValueError("請選擇按月或按季。")
    year, period = int(year), int(period)
    if not 1900 <= year <= 9999:
        raise ValueError("年份須介於 1900 至 9999。")
    if not 1 <= period <= (12 if period_type == "month" else 4):
        raise ValueError("月份或季度不正確。")
    first_month = period if period_type == "month" else (period - 1) * 3 + 1
    last_month = first_month if period_type == "month" else first_month + 2
    return date(year, first_month, 1), date(year, last_month, monthrange(year, last_month)[1])
