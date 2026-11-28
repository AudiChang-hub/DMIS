"""訂單頁「原廠代墊／代轉」小區塊（T-334）：區塊自己取資料，不改訂單頁的 context。"""
from django import template

register = template.Library()


@register.inclusion_tag("sales/_manufacturer_advance_block.html", takes_context=True)
def manufacturer_advance_block(context, order):
    from sales.manufacturer_advance_views import block_context

    request = context.get("request")
    return {**block_context(request, order), "request": request, "csrf_token": context.get("csrf_token")}
