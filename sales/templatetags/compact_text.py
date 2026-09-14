from django import template

register = template.Library()


@register.simple_tag
def compact_value(value, limit):
    value = str(value or "—")
    limit = int(limit)
    return {"shortened": len(value) > limit, "preview": value[:limit - 1] + "…" if len(value) > limit else value}
