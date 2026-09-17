"""可維護說明的固定白名單，不接受任意模板、HTML 或程式片段。"""
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).resolve().parent.parent / "site_copy_catalog.json").read_text(encoding="utf-8"))


def text_for(request, key):
    from sales.models import SiteTextOverride
    entries = catalog()
    if key not in entries:
        return ""
    if not hasattr(request, "_site_text_overrides"):
        request._site_text_overrides = dict(SiteTextOverride.objects.values_list("key", "text"))
    return request._site_text_overrides.get(key, entries[key]["default"])


def print_copy(pdf, key, default):
    from types import SimpleNamespace
    if not hasattr(pdf, "_site_copy_context"):
        pdf._site_copy_context = SimpleNamespace()
    code = "print." + key
    return text_for(pdf._site_copy_context, code) if code in catalog() else default
