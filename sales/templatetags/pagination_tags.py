from urllib.parse import urlencode

from django import template
from django.http import QueryDict


register = template.Library()


@register.inclusion_tag("sales/_pagination.html", takes_context=True)
def pagination(context, page_obj, aria_label="分頁", anchor="", drop="", page_param="page", query=None, mode=""):
    """Render the shared pagination controls while preserving active filters."""
    if not page_obj or not page_obj.paginator.num_pages:
        return {"page_obj": None}

    request = context["request"]
    dropped_keys = {page_param}
    dropped_keys.update(key.strip() for key in drop.split(",") if key.strip())
    preserved_params = [
        (key, value)
        for key, values in (request.GET if query is None else QueryDict(query)).lists()
        if key not in dropped_keys
        for value in values
    ]
    fragment = f"#{anchor.lstrip('#')}" if anchor else ""

    def page_url(page_number):
        query = urlencode([*preserved_params, (page_param, page_number)])
        return f"?{query}{fragment}"

    return {
        "page_obj": page_obj,
        "request": request,
        "page_param": page_param,
        "mode": mode,
        "aria_label": aria_label,
        "fragment": fragment,
        "hidden_params": preserved_params,
        "first_url": page_url(1),
        "previous_url": (
            page_url(page_obj.previous_page_number())
            if page_obj.has_previous()
            else ""
        ),
        "next_url": (
            page_url(page_obj.next_page_number()) if page_obj.has_next() else ""
        ),
        "last_url": page_url(page_obj.paginator.num_pages),
    }
