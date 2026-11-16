import json

from django import template


register = template.Library()


@register.filter
def crop_json(value):
    """證件裁切參數（T-190）放進隱藏欄位；沒有參數時留空。"""
    return json.dumps(value, ensure_ascii=False) if value else ""
