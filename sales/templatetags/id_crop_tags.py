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


@register.filter
def id_copy_label(order):
    """訂單頁「列印與簽署文件」的影本入口（T-208）：適用時回傳「身分證」或「居留證」，不適用回傳空字串。"""
    from sales.services import form_print

    return form_print.id_copy_document_label(order) if form_print.id_copy_applies(order) else ""
