from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from .access.views import root_required
from .models import SiteTextOverride, SiteTextRevision
from .services.site_copy import catalog


class TextForm(forms.Form):
    text = forms.CharField(label="顯示文字", max_length=10000, widget=forms.Textarea(attrs={"rows": 7}))
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)


@root_required
@require_http_methods(["GET", "POST"])
def manage(request):
    entries = catalog()
    key = request.GET.get("key", "")
    if key and key not in entries:
        raise Http404
    overrides = {item.key: item for item in SiteTextOverride.objects.all()}
    item = overrides.get(key)
    initial = {"text": item.text if item else entries.get(key, {}).get("default", ""), "version": item.version if item else 0}
    form = TextForm(request.POST or None, initial=initial)
    limit = entries.get(key, {}).get("max_length", 10000)
    form.fields["text"].widget.attrs["maxlength"] = limit
    status = 200
    if request.method == "POST":
        if not key:
            raise Http404
        if form.is_valid():
            if len(form.cleaned_data["text"]) > limit or (key.startswith("print.") and "\n" in form.cleaned_data["text"]):
                form.add_error("text", f"此列印欄位最多 {limit} 字，請使用單段文字，以免超出紙本範圍。")
        if not form.errors:
            with transaction.atomic():
                # 唯一鍵建立占位後鎖定同一文案；不同管理員也不可互相覆寫。
                SiteTextOverride.objects.get_or_create(key=key, defaults={"text": entries[key]["default"], "version": 0})
                current = SiteTextOverride.objects.select_for_update().get(key=key)
                if form.cleaned_data["version"] != (current.version if current else 0):
                    form.add_error(None, "文字已被另一個視窗更新，請重新載入後再編輯。")
                    status = 409
                else:
                    before = current.text if current else entries[key]["default"]
                    after = entries[key]["default"] if request.POST.get("action") == "reset" else form.cleaned_data["text"]
                    SiteTextOverride.objects.update_or_create(key=key, defaults={"text": after, "version": current.version + 1 if current else 1, "updated_by": request.user.get_username()})
                    SiteTextRevision.objects.create(key=key, before=before, after=after, actor=request.user.get_username())
                    messages.success(request, "說明文字已更新。")
                    return redirect(request.get_full_path())
    query = request.GET.get("q", "").strip().casefold()
    page_filter = request.GET.get("section", "")
    scope = request.GET.get("scope", "")
    words = query.split()
    rows = [{"key": code, **entry, "current": overrides[code].text if code in overrides else entry["default"], "customized": code in overrides} for code, entry in entries.items()
            if (scope != "print" or code.startswith("print.")) and (scope != "screen" or not code.startswith("print."))
            and (request.GET.get("customized") != "1" or code in overrides)
            and (not page_filter or entry["page"] == page_filter)
            and all(word in (code + entry["default"] + entry["page"] + (overrides[code].text if code in overrides else "")).casefold() for word in words)]
    return render(request, "sales/site_copy_manage.html", {"entry": entries.get(key), "key": key, "form": form,
        "sections": sorted({e["page"] for e in entries.values()}), "page_obj": Paginator(rows, 20).get_page(request.GET.get("page")),
        "revisions": SiteTextRevision.objects.filter(key=key)[:10] if key else []}, status=status)
