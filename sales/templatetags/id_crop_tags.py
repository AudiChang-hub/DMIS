import json

from django import template


register = template.Library()


@register.filter
def crop_json(value):
    """證件裁切參數（T-190）放進隱藏欄位；沒有參數時留空。"""
    return json.dumps(value, ensure_ascii=False) if value else ""


@register.simple_tag
def id_card_view(instance, field_name, model_name="order"):
    """訂單明細的證件：裁切卡片網址、原圖網址、是否建議確認裁切（T-199／T-200）。"""
    from sales.services.id_card_crop import card_view

    return card_view(instance, model_name, field_name)
