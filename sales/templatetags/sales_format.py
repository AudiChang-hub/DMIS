from decimal import Decimal, InvalidOperation

from django import template

from sales.services.registration_fee import registration_rate_label as build_registration_rate_label


register = template.Library()


@register.filter
def number_with_commas(value):
    """用固定千分位呈現金額，不受伺服器語系設定影響。"""
    try:
        number = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return value
    return f"{number:,.0f}"


@register.filter
def registration_rate_label(value, displacement_cc=None):
    """僅對油車費率顯示排氣量級距，不暴露內部 M2～M5 代碼。"""
    return build_registration_rate_label(value, displacement_cc)


@register.filter
def roc_date(value):
    """民國日期，例如「民國 81 年 1 月 21 日」；民國前（1911 年以前）回傳西元。"""
    if not value:
        return ""
    year = value.year - 1911
    if year <= 0:
        return f"{value.year} 年 {value.month} 月 {value.day} 日"
    return f"民國 {year} 年 {value.month} 月 {value.day} 日"
