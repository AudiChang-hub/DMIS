from django import template

from sales.services.tax_consent_pdf import needs_tax_consent as _needs_tax_consent

register = template.Library()


@register.filter
def needs_tax_consent(order):
    """列印勾選畫面：SUZUKI 油車且有汰舊時，多一個「欣鈴退稅同意書」勾選（T-158）。"""
    return _needs_tax_consent(order)
