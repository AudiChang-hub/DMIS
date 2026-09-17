from django import template
from django.utils.html import conditional_escape
from sales.services.site_copy import catalog, text_for

register = template.Library()


@register.simple_tag(takes_context=True)
def site_help(context, value):
    import hashlib
    key = "field_help." + hashlib.sha256(str(value).encode()).hexdigest()[:12]
    request = context.get("request")
    return conditional_escape(text_for(request, key) if request and key in catalog() else value)


@register.simple_tag(takes_context=True)
def site_text(context, key):
    request = context.get("request")
    value = text_for(request, key) if request else catalog().get(key, {}).get("default", "")
    return conditional_escape(value)


@register.inclusion_tag('sales/_page_back.html', takes_context=True)
def site_navigation(context):
    from django.urls import reverse
    from sales.access.services import policy_for
    from sales.access.registry import ROUTES, BY_KEY, ROOT_ONLY
    request = context['request']
    route = request.resolver_match.url_name
    policy = policy_for(request)
    parent, label = 'dashboard', '首頁'
    if route in ROOT_ONLY:
        parent, label = 'data_maintenance', '資料維護區'
    elif route in {'catalog_detail', 'order_start', 'order_submitted'}:
        parent, label = 'catalog', '建立訂單'
    elif route in ROUTES:
        screen = BY_KEY.get(ROUTES[route][0])
        if screen:
            parent, label = screen.route, screen.label
    if parent == route or not policy.route(parent):
        parent, label = 'dashboard', '首頁'
    return {'fallback_url': reverse(parent), 'label': label,
            'root_url': reverse('dashboard') if parent != 'dashboard' else '', 'root_label': '首頁'}
