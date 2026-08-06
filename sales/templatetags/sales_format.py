from decimal import Decimal, InvalidOperation

from django import template


register = template.Library()


@register.filter
def number_with_commas(value):
    """用固定千分位呈現金額，不受伺服器語系設定影響。"""
    try:
        number = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return value
    return f"{number:,.0f}"
