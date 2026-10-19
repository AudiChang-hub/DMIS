from django import template

from sales.services.order_origin import order_origin

register = template.Library()


@register.inclusion_tag("sales/_order_origin.html")
def order_origin_badge(order, detail=False):
    """訂單編號下方的來源標記；列表須先 with_order_origin／attach_order_origin，否則每張訂單多查一次。"""
    return {"origin": order_origin(order), "detail": detail}
