"""資料維護區「配件與工資」清單（T-178）：依類別分頁籤、清單上直接批次修改、刪除沒用過的配件。

- 批次修改沿用單筆表單的驗證（名稱不重複、金額格式），全部通過才一起存；任一筆有錯就都不存。
- 售價與工資是訂單當時的快照，這裡修改只影響之後新選的配件，已建立的訂單不變。
- 訂單配件對主檔是 PROTECT：有訂單用過的配件不能刪，改用停用或合併（T-138）。
- 刪除與批次修改寫進 Django 內建的異動紀錄（admin LogEntry），不另建資料表。
- 一個配件可屬於多個類別（T-179）：各類別頁籤都列出它、筆數各算一次；「全部」是不重複的筆數。
"""
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.admin.models import CHANGE, DELETION, LogEntry
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Prefetch, ProtectedError, Q
from django.http import QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .forms import AccessoryProductBulkForm
from .models import AccessoryCategory, AccessoryProduct

LIST_PARAMS = ("q", "active", "category", "page")
BULK_FIELDS = ("name", "categories", "sale_price", "labor_fee", "cost", "active")


def _sorted_categories():
    return Prefetch("categories", queryset=AccessoryCategory.objects.order_by("sort_order", "name"))


def _filters(params):
    return {
        "q": (params.get("q") or "").strip(),
        "active": params.get("active") if params.get("active") in {"yes", "no"} else "",
        "category": (params.get("category") or "").strip(),
        "page": params.get("page") or "",
    }


def _list_url(selected, **overrides):
    query = {key: selected.get(key, "") for key in LIST_PARAMS}
    query.update(overrides)
    query = {key: value for key, value in query.items() if value}
    return reverse("accessory_product_list") + (f"?{urlencode(query)}" if query else "")


def _category_tabs(selected, base):
    """頁籤：全部＋每個類別（停用的類別有配件才列），未分類有配件才列；筆數套用目前的搜尋與狀態篩選。"""
    counts = {row["categories"]: row["n"] for row in base.order_by().values("categories").annotate(n=Count("id", distinct=True))}
    edit = "1" if selected.get("edit") else ""
    tabs = [{"key": "", "label": "全部", "count": base.count()}]
    for category in AccessoryCategory.objects.order_by("sort_order", "name"):
        count = counts.get(category.pk, 0)
        key = str(category.pk)
        if category.active or count or selected["category"] == key:
            tabs.append({"key": key, "label": category.name, "count": count})
    if counts.get(None) or selected["category"] == "none":
        tabs.append({"key": "none", "label": "未分類", "count": counts.get(None, 0)})
    for tab in tabs:
        tab["active"] = tab["key"] == selected["category"]
        tab["url"] = _list_url(selected, category=tab["key"], page="", edit=edit)
    if not any(tab["active"] for tab in tabs):
        tabs[0]["active"] = True
    return tabs


def _list_context(selected, bound_forms=None):
    base = AccessoryProduct.objects.all()
    if selected["q"]:
        base = base.filter(Q(name__icontains=selected["q"]) | Q(note__icontains=selected["q"]))
    if selected["active"] == "yes":
        base = base.filter(active=True)
    elif selected["active"] == "no":
        base = base.filter(active=False)
    tabs = _category_tabs(selected, base)
    products = base
    if selected["category"] == "none":
        products = products.filter(categories__isnull=True)
    elif selected["category"].isdigit():
        products = products.filter(categories=int(selected["category"]))
    products = products.prefetch_related(_sorted_categories()).annotate(usage_count=Count("order_lines", distinct=True)).order_by("name")
    page = Paginator(products, 100).get_page(selected["page"])
    bound_forms = bound_forms or {}
    rows = []
    for product in page.object_list:
        form = bound_forms.get(product.pk)
        rows.append({
            "product": product,
            "form": form or AccessoryProductBulkForm(instance=product, prefix=f"p{product.pk}"),
            "bound": form is not None,
            "version": product.updated_at.isoformat(),
        })
    categories = list(AccessoryCategory.objects.filter(
        Q(active=True) | Q(pk__in={category.pk for row in rows for category in row["product"].categories.all()})
    ).order_by("sort_order", "name"))
    for row in rows:
        # 批次修改的類別勾選（T-179 可複選）：目前勾選（送出失敗時帶回輸入）與原本的類別。
        original = {category.pk for category in row["product"].categories.all()}
        checked = {int(value) for value in (row["form"]["categories"].value() or []) if str(value).isdigit()}
        row["category_choices"] = [
            {"pk": category.pk, "name": category.name, "active": category.active,
             "checked": category.pk in checked, "original": category.pk in original}
            for category in categories
        ]
    current_tab = next(tab for tab in tabs if tab["active"])
    return {
        "rows": rows,
        "page_obj": page,
        "tabs": tabs,
        "current_tab": current_tab,
        "selected": selected,
        "categories": categories,
        "clear_url": _list_url({"category": selected["category"]}, edit=selected.get("edit", "")),
        "edit_url": _list_url(selected, edit="1"),
        "view_url": _list_url(selected),
        "return_query": urlencode({key: selected[key] for key in LIST_PARAMS if selected.get(key)}),
    }


def _category_names(product):
    return "、".join(category.name for category in product.sorted_categories()) or "未分類"


def _display(field, value):
    if field == "categories":
        return value or "未分類"
    if field == "active":
        return "啟用中" if value else "已停用"
    if field == "cost" and value is None:
        return "未維護"
    return str(value)


def _log(request, product, flag, message):
    LogEntry.objects.create(
        user_id=request.user.pk,
        content_type=ContentType.objects.get_for_model(AccessoryProduct),
        object_id=str(product.pk),
        object_repr=product.name[:200],
        action_flag=flag,
        change_message=message,
    )


def _bulk_update(request, selected):
    ids = list(dict.fromkeys(int(value) for value in request.POST.getlist("row") if value.isdigit()))
    if not ids:
        messages.info(request, "沒有修改任何配件。")
        return redirect(_list_url(selected))
    with transaction.atomic():
        products = {product.pk: product for product in AccessoryProduct.objects.select_for_update().filter(pk__in=ids)}
        forms, changed, before, names = {}, [], {}, {}
        for pk in ids:
            product = products.get(pk)
            if product is None:
                continue  # 別人已刪除；這一列略過
            before[pk] = {field: _category_names(product) if field == "categories" else getattr(product, field) for field in BULK_FIELDS}
            form = AccessoryProductBulkForm(request.POST, instance=product, prefix=f"p{pk}")
            forms[pk] = form
            if not form.is_valid():
                continue
            if not form.has_changed():
                continue
            version = request.POST.get(f"p{pk}-version")
            if version and version != product.updated_at.isoformat():
                form.add_error(None, "這一項剛被其他人修改過，請重新整理後再改。")
                continue
            name_key = form.cleaned_data["name"]
            if name_key in names:
                form.add_error("name", f"和這次一起修改的另一項同名（{name_key}）。")
                continue
            names[name_key] = pk
            changed.append(form)
        invalid = [form for form in forms.values() if form.errors]
        if invalid:
            transaction.set_rollback(True)
        else:
            _save_changes(request, changed, before)
    if invalid:
        messages.error(request, f"有 {len(invalid)} 項沒通過檢查，所有修改都還沒套用；請修正標紅的欄位後再按「套用修改」。")
        # 送出的列帶回輸入值與錯誤，其他列照資料庫顯示。
        context = _list_context({**selected, "edit": "1"}, bound_forms=forms)
        return render(request, "sales/accessory_product_list.html", context, status=400)
    if changed:
        messages.success(request, f"已套用 {len(changed)} 項配件的修改。已建立的訂單維持當時的售價與工資。")
    else:
        messages.info(request, "沒有修改任何配件。")
    return redirect(_list_url(selected))


def _save_changes(request, changed, before):
    for form in changed:
        product = form.save()
        old = before[product.pk]
        after = {field: _category_names(product) if field == "categories" else getattr(product, field) for field in BULK_FIELDS}
        diffs = [
            f"{AccessoryProduct._meta.get_field(field).verbose_name}：{_display(field, old[field])} → {_display(field, after[field])}"
            for field in BULK_FIELDS if old[field] != after[field]
        ]
        _log(request, product, CHANGE, "配件清單批次修改：" + "；".join(diffs))


@login_required
@require_http_methods(["GET", "POST"])
def accessory_product_list(request):
    if request.method == "POST":
        # 批次修改送到同一頁（POST 需「配件與工資」的操作權限，與單筆編輯相同）。
        return _bulk_update(request, _filters(QueryDict(request.POST.get("return_query", ""))))
    selected = _filters(request.GET)
    selected["edit"] = "1" if request.GET.get("edit") == "1" else ""
    return render(request, "sales/accessory_product_list.html", _list_context(selected))


@login_required
@require_http_methods(["POST"])
@transaction.atomic
def accessory_product_delete(request, pk):
    """刪除沒有任何訂單用過的配件；用過的不能刪（訂單配件對主檔是 PROTECT），請改用停用或合併。"""
    product = get_object_or_404(AccessoryProduct.objects.select_for_update(), pk=pk)
    back = _list_url(_filters(QueryDict(request.POST.get("return_query", ""))))
    used = product.order_lines.count()
    if used:
        messages.error(request, f"「{product.name}」已有 {used} 筆訂單配件用過，不能刪除；可以改成停用，或到編輯頁合併到其他配件。")
        return redirect(back)
    name = product.name
    _log(request, product, DELETION, f"刪除配件（沒有訂單用過）：類別 {_category_names(product)}；售價 {product.sale_price}；工資 {product.labor_fee}")
    try:
        with transaction.atomic():
            product.delete()
    except ProtectedError:
        transaction.set_rollback(True)
        messages.error(request, f"「{name}」剛被訂單用到，不能刪除；可以改成停用，或到編輯頁合併到其他配件。")
        return redirect(back)
    messages.success(request, f"已刪除配件「{name}」。之後在訂單加購列自行填寫同名配件時，存檔會再自動加回清單。")
    return redirect(back)
