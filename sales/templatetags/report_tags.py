"""T-311 報表模板用：車型 X 顏色（#10）長條旁的實車顏色圓點，沿用 car_colors 的色系判斷（不改原本規則）。"""
from django import template

from sales.reporting.car_colors import FAMILIES, car_color_family, outline

register = template.Library()
_BASE = {family: shades[0] for family, _keywords, shades in FAMILIES}


@register.filter
def car_paint(label):
    """車色名稱 → 該色系的基本色碼；對不到色系回空字串（畫面不畫圓點）。"""
    return _BASE.get(car_color_family(str(label or "")), "")


@register.filter
def car_paint_outline(color):
    """很淺的顏色（白）在白底看不到，圓點要加框。"""
    return bool(color) and outline(color)
