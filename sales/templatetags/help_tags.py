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


@register.inclusion_tag("help/_page_tip.html", takes_context=True)
def help_page_tip(context):
    """功能頁頁首的「這頁做什麼、下一步去哪」（T-201 c）；只在 PAGE_TIPS 列的頁面出現。"""
    from sales.access.services import policy_for
    from sales.help import page_tip
    request = context.get("request")
    match = getattr(request, "resolver_match", None)
    return {"page_tip": page_tip(policy_for(request), match.url_name) if match else None}


@register.inclusion_tag("help/_start_card.html", takes_context=True)
def help_start_card(context):
    """首頁新手卡片（T-201 b）：看得到「從這裡開始」主線的人才顯示；關閉後記在這台裝置的 localStorage。"""
    from sales.access.services import policy_for
    from sales.help import start_stops
    request = context.get("request")
    visible = bool(request) and any(item["article"] for item in start_stops(policy_for(request)))
    return {"start_visible": visible}
