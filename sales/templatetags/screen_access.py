from django import template
from django.urls import NoReverseMatch, resolve, reverse

from sales.access.services import policy_for

register = template.Library()


@register.simple_tag(takes_context=True)
def can_access(context, name, *args):
    request = context.get("request")
    if request is None:
        return False
    kwargs = {}
    if args:
        try:
            kwargs = resolve(reverse(name, args=args)).kwargs
        except (NoReverseMatch, ValueError):
            return False
    return policy_for(request).route(name, kwargs=kwargs)


class AccessNode(template.Node):
    def __init__(self, expressions, nodes):
        self.expressions, self.nodes = expressions, nodes

    def render(self, context):
        values = [expr.resolve(context) for expr in self.expressions]
        return self.nodes.render(context) if can_access(context, *values) else ""


@register.tag
def if_access(parser, token):
    expressions = [parser.compile_filter(value) for value in token.split_contents()[1:]]
    if not expressions:
        raise template.TemplateSyntaxError("if_access 需要路由名稱")
    nodes = parser.parse(("endif_access",))
    parser.delete_first_token()
    return AccessNode(expressions, nodes)
