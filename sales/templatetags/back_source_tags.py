from urllib.parse import urlsplit

from django import template
from django.utils.safestring import mark_safe

from sales.back_source import is_link_source, resolve_back_source

register = template.Library()


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
