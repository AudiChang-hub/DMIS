"""使用說明文字標記：[[按鈕名稱]] → 畫面字樣，**重點** → 粗體；其餘一律跳脫。"""
import re

from django import template
from django.templatetags.static import static
from django.utils.html import escape
from django.utils.safestring import mark_safe

from sales.help.schema import SCREEN_DIR

register = template.Library()

UI = re.compile(r"\[\[(.+?)\]\]")
BOLD = re.compile(r"\*\*(.+?)\*\*")


@register.filter
def help_markup(value):
    text = escape(value or "")
    text = UI.sub(r'<span class="help-ui">\1</span>', text)
    text = BOLD.sub(r"<b>\1</b>", text)
    return mark_safe(text)


@register.simple_tag
def help_screen(figure):
    return static(f"{SCREEN_DIR}/{figure.src}")
