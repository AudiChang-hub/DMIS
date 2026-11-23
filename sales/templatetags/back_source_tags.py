from urllib.parse import urlsplit

from django import template
from django.utils.safestring import mark_safe

from sales.back_source import is_link_source, resolve_back_source

register = template.Library()

# 右下角懸浮鈕（T-297）照抄返回列實際顯示的來源，存在 request 上，base.html 的 page_dock 在 </main> 之後讀。
DOCK_SOURCE_ATTR = "_page_dock_source"


@register.simple_tag(takes_context=True)
def page_back_source(context, fallback_url=""):
    """返回列的來源（T-291）：合法的 back_to 才有值；來源就是原本的上一層時只換網址（same_parent）。"""
    source = resolve_back_source(context.get("request"))
    if source:
        source["same_parent"] = source["path"] == urlsplit(str(fallback_url or "")).path
    return source


@register.simple_tag(takes_context=True)
def link_source_attr(context):
    request = context.get("request")
    return mark_safe(" data-link-source") if request is not None and is_link_source(request) else ""


@register.simple_tag(takes_context=True)
def page_dock_source(context, url, label):
    """返回列顯示「← 來源」時記下同一組網址與名稱（_page_back.html 呼叫），懸浮鈕不另判斷。"""
    request = context.get("request")
    if request is not None and url and label:
        setattr(request, DOCK_SOURCE_ATTR, {"url": str(url), "label": str(label)})
    return ""


@register.inclusion_tag("sales/_page_dock.html", takes_context=True)
def page_dock(context):
    """右下角懸浮鈕（T-297）：「↑」回頂端；返回列有顯示來源時加「← 來源名稱」。訂單頁精簡列已有返回鍵，只放「↑」。"""
    request = context.get("request")
    match = getattr(request, "resolver_match", None)
    source = getattr(request, DOCK_SOURCE_ATTR, None) if request is not None else None
    if match is not None and match.url_name == "order_detail":
        source = None
    return {"dock_source": source}
