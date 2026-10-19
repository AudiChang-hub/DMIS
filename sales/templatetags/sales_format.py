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


# 色名裡的基本色字 → 色點色調（app.css `.color-dot` 的 --hue-*）。只是辨識用的示意，不代表原廠色票。
COLOR_HUE_CHARS = {
    "白": "white", "黑": "black", "灰": "gray", "銀": "silver", "藍": "blue", "青": "teal",
    "綠": "green", "紅": "red", "橘": "orange", "橙": "orange", "黃": "yellow", "金": "gold",
    "棕": "brown", "咖": "brown", "褐": "brown", "紫": "purple", "粉": "pink", "米": "beige",
}


@register.filter
def color_swatch_style(name):
    """依色名給色點：取出現的前兩個基本色（維蘇威黑→黑、黑紅→黑＋紅雙色），認不出的色名顯示中性色點。"""
    hues = []
    for char in str(name or "").replace("金屬", ""):
        hue = COLOR_HUE_CHARS.get(char)
        if hue and hue not in hues:
            hues.append(hue)
    if not hues:
        return ""
    return f"--dot-a: var(--hue-{hues[0]}); --dot-b: var(--hue-{hues[1] if len(hues) > 1 else hues[0]})"


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
