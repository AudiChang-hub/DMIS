"""訂單頁表單 widget 的快速輸出（T-281 h，使用者 2026-11-21 選 B）。

正式站訂單頁約 60% 的模板時間花在 Django 內建的 widget 模板（attrs.html 每頁 776 次、select／option、input）。
這裡用 Python 直接組出和內建模板逐字相同的 HTML，只套用在訂單頁的表單（`use_fast_widgets`），其他頁面不受影響。

- 只處理內建的 attrs／input 系列／select／select_option／textarea；啟動時核對模板原文，
  與本檔照抄的內容不同（例如升級 Django）就整個停用、改回原本的模板。
- 遇到模板會呼叫的 callable、自訂 option 模板等少見情況，該 widget 直接交回原本的模板。
- 輸出與原模板相同的跳脫、在地化與時區轉換（render_value_in_context）；最後一樣 strip()。
"""
from django.forms import BaseForm
from django.forms.formsets import BaseFormSet
from django.forms.renderers import DjangoTemplates
from django.template.defaultfilters import stringformat
from django.utils.formats import localize
from django.utils.html import conditional_escape
from django.utils.safestring import SafeData
from django.utils.timezone import template_localtime

WIDGETS = "django/forms/widgets/"
ATTRS = (
    "{% for name, value in widget.attrs.items %}{% if value is not False %} {{ name }}{% if value is not True %}"
    "=\"{{ value|stringformat:'s' }}\"{% endif %}{% endif %}{% endfor %}"
)
INPUT = (
    '<input type="{{ widget.type }}" name="{{ widget.name }}"{% if widget.value != None %} '
    "value=\"{{ widget.value|stringformat:'s' }}\"{% endif %}{% include \"django/forms/widgets/attrs.html\" %}>"
)
INCLUDE_INPUT = '{% include "django/forms/widgets/input.html" %}'
OPTION = (
    "<option value=\"{{ widget.value|stringformat:'s' }}\"{% include \"django/forms/widgets/attrs.html\" %}>"
    "{{ widget.label }}</option>"
)
SELECT = (
    '<select name="{{ widget.name }}"{% include "django/forms/widgets/attrs.html" %}>'
    "{% for group_name, group_choices, group_index in widget.optgroups %}{% if group_name %}\n"
    '  <optgroup label="{{ group_name }}">{% endif %}{% for option in group_choices %}\n'
    "  {% include option.template_name with widget=option %}{% endfor %}{% if group_name %}\n"
    "  </optgroup>{% endif %}{% endfor %}\n</select>"
)
TEXTAREA = (
    '<textarea name="{{ widget.name }}"{% include "django/forms/widgets/attrs.html" %}>\n'
    "{% if widget.value %}{{ widget.value }}{% endif %}</textarea>"
)
INPUT_FAMILY = ("text", "number", "email", "url", "password", "hidden", "date", "datetime", "time", "search", "tel",
                "checkbox", "file", "color")


class _Slow(Exception):
    """交回原本的模板。"""


def _plain(value):
    if callable(value):
        raise _Slow
    return value


def _var(value):
    """{{ value }}：與 django.template.base.render_value_in_context 相同。"""
    value = localize(template_localtime(_plain(value), use_tz=None), use_l10n=None)
    if not issubclass(type(value), str):
        value = str(value)
    return conditional_escape(value)


def _format(value):
    """{{ value|stringformat:'s' }}：stringformat 是 is_safe 篩選器，輸入已標記安全時不再跳脫。"""
    value = _plain(value)
    result = stringformat(value, "s")
    return result if isinstance(value, SafeData) else conditional_escape(result)


class FastWidgetRenderer(DjangoTemplates):
    def __init__(self):
        super().__init__()
        self._suffix = self._verified_suffixes()

    def _verified_suffixes(self):
        """各模板原文去掉本檔照抄的內容後剩下的結尾空白；任何一個對不上就全部停用。"""
        expected = {"attrs": ATTRS, "input": INPUT, "select_option": OPTION, "select": SELECT, "textarea": TEXTAREA,
                    **{name: INCLUDE_INPUT for name in INPUT_FAMILY}}
        suffixes = {}
        for name, body in expected.items():
            try:
                source = self.engine.get_template(f"{WIDGETS}{name}.html").template.source
            except Exception:
                return {}
            if not source.startswith(body) or source[len(body):].strip():
                return {}
            suffixes[name] = source[len(body):]
        return suffixes

    def render(self, template_name, context, request=None):
        if self._suffix and request is None and template_name.startswith(WIDGETS):
            name = template_name[len(WIDGETS):-len(".html")] if template_name.endswith(".html") else ""
            try:
                if name == "select":
                    return self._select(context["widget"]).strip()
                if name == "textarea":
                    return self._textarea(context["widget"]).strip()
                if name in INPUT_FAMILY:
                    return (self._input(context["widget"]) + self._suffix[name]).strip()
            except (_Slow, KeyError, TypeError, AttributeError):
                pass
        return super().render(template_name, context, request)

    def _attrs(self, widget):
        attrs = _plain(widget["attrs"])
        if not isinstance(attrs, dict) or "items" in attrs:
            raise _Slow
        parts = []
        for name, value in attrs.items():
            if value is not False:
                parts.append(" " + _var(name))
                if value is not True:
                    parts.append('="' + _format(value) + '"')
        return "".join(parts) + self._suffix["attrs"]

    def _input(self, widget):
        value = _plain(widget["value"])
        html = '<input type="' + _var(widget["type"]) + '" name="' + _var(widget["name"]) + '"'
        if value != None:  # noqa: E711 與模板的 != None 相同
            html += ' value="' + _format(value) + '"'
        return html + self._attrs(widget) + ">" + self._suffix["input"]

    def _option(self, option):
        if option.get("template_name") != f"{WIDGETS}select_option.html":
            raise _Slow
        return ('<option value="' + _format(option["value"]) + '"' + self._attrs(option) + ">"
                + _var(option["label"]) + "</option>" + self._suffix["select_option"])

    def _select(self, widget):
        parts = ['<select name="', _var(widget["name"]), '"', self._attrs(widget), ">"]
        for group_name, group_choices, _group_index in _plain(widget["optgroups"]):
            if _plain(group_name):
                parts += ['\n  <optgroup label="', _var(group_name), '">']
            for option in group_choices:
                parts += ["\n  ", self._option(option)]
            if group_name:
                parts.append("\n  </optgroup>")
        parts.append("\n</select>" + self._suffix["select"])
        return "".join(parts)

    def _textarea(self, widget):
        value = _plain(widget["value"])
        return ('<textarea name="' + _var(widget["name"]) + '"' + self._attrs(widget) + ">\n"
                + (_var(value) if value else "") + "</textarea>" + self._suffix["textarea"])


_renderer = None


def fast_renderer():
    global _renderer
    if _renderer is None:
        _renderer = FastWidgetRenderer()
    return _renderer


def use_fast_widgets(context, *, depth=2):
    """把 context 裡的表單與 formset（含 formset 的每一列與新增列）改用快速輸出；回傳 context。"""
    renderer = fast_renderer()
    seen = set()

    def visit(value, level):
        if id(value) in seen:
            return
        seen.add(id(value))
        if isinstance(value, BaseForm):
            value.renderer = renderer
        elif isinstance(value, BaseFormSet):
            value.renderer = renderer
            for form in value.forms:
                form.renderer = renderer
        elif level > 0 and isinstance(value, dict):
            for item in value.values():
                visit(item, level - 1)
        elif level > 0 and isinstance(value, (list, tuple)):
            for item in value:
                visit(item, level - 1)

    visit(context, depth + 1)
    return context
