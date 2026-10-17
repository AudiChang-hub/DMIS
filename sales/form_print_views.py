"""套表列印：一次勾選多張訂單、每張各自要印的套表；信封出 Word 檔，聲明書與簽收單出 A4 PDF。"""
from io import BytesIO
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import FileResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from sales.models import OrderEvent, SalesOrder
from sales.services import form_print, order_tabs
from sales.services.order_intake import scoped_orders
from sales.services.order_search import build_order_search_query

PAGE_SIZE = 30
MAX_JOBS = 300
TAB_CHOICES = (("open", "進行中"), ("delivered", "已交車"), ("all", "全部"))


def _orders(user):
    return scoped_orders(user).exclude(status=SalesOrder.Status.DRAFT).select_related(
        "source", "vehicle_model", "color", "allocated_vehicle", "operations",
        "installment_company_master", "legacy_snapshot",
    )


def _row(order):
    values = form_print.form_values(order)
    warnings = form_print.form_warnings(order, values)
    suggested = form_print.suggested_forms(order, values)
    return {
        "order": order,
        "values": values,
        "electric": order.is_electric_vehicle,
        "forms": [
            {
                "spec": spec,
                "label": f"{spec.label}・{'電車' if order.is_electric_vehicle else '油車'}" if spec.key == "envelope" else spec.label,
                "warnings": warnings[spec.key],
                "suggested": spec.key in suggested,
            }
            for spec in form_print.FORMS
        ],
        "receipt_note": form_print.default_receipt_note(values),
    }


@login_required
def form_print_page(request):
    orders = _orders(request.user)
    query = request.GET.get("q", "").strip()
    tab = request.GET.get("tab", "")
    if query:
        orders = orders.filter(build_order_search_query(query, profit_unlocked=False)).distinct()
        tab = tab if tab in dict(TAB_CHOICES) else "all"
    elif tab not in dict(TAB_CHOICES):
        tab = "open"
    if tab != "all":
        orders = order_tabs.with_subsidy_progress(orders).filter(order_tabs.tab_filter(tab))
    orders = orders.order_by("-order_date", "-pk")
    page = Paginator(orders, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "sales/form_print.html", {
        "page_obj": page,
        "rows": [_row(order) for order in page.object_list],
        "forms": form_print.FORMS,
        "query": query,
        "tab": tab,
        "tab_choices": TAB_CHOICES,
        "field_sources": form_print.FORM_FIELD_SOURCES,
    })


def _parse_jobs(request):
    picked = []
    seen = set()
    for raw in request.POST.getlist("job")[: MAX_JOBS + 1]:
        pk, _, form = raw.partition(":")
        if not pk.isdigit() or form not in form_print.FORM_KEYS or (pk, form) in seen:
            continue
        seen.add((pk, form))
        picked.append((int(pk), form))
    return picked


def _picked_orders(request, forms):
    """勾選且仍在權限範圍內的 (訂單, 套表)，依勾選順序；錯誤時回傳要導回的 response。"""
    picked = _parse_jobs(request)
    if not picked:
        messages.error(request, "請至少勾選一張訂單的一份套表。")
        return None, redirect("form_print")
    if len(picked) > MAX_JOBS:
        messages.error(request, f"一次最多列印 {MAX_JOBS} 份，請分批列印。")
        return None, redirect("form_print")
    picked = [(pk, form) for pk, form in picked if form in forms]
    if not picked:
        kind = "信封" if forms == ("envelope",) else "聲明書或簽收單"
        messages.error(request, f"勾選的項目裡沒有{kind}。")
        return None, redirect("form_print")
    orders = _orders(request.user).in_bulk({pk for pk, _form in picked})
    # 不在權限範圍或已刪除：略過，不透露是否存在。
    found = [(orders[pk], form) for pk, form in picked if pk in orders]
    if not found:
        messages.error(request, "勾選的訂單已不存在或沒有權限列印。")
        return None, redirect("form_print")
    return found, None


def _file_response(content, *, content_type, ascii_name, quoted_name, inline):
    response = FileResponse(BytesIO(content), content_type=content_type)
    disposition = "inline" if inline else "attachment"
    response["Content-Disposition"] = f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted_name}"
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@require_POST
def form_print_pdf(request):
    found, error = _picked_orders(request, ("tax_declaration", "receipt"))
    if error:
        return error
    jobs = []
    for order, form in found:
        note = address = ""
        if form == "receipt":
            note = request.POST.get(f"note_{order.pk}", "").strip()[: form_print.NOTE_MAX_CHARS]
            address = request.POST.get(f"address_{order.pk}", "").strip()[: form_print.ADDRESS_MAX_CHARS]
        jobs.append(form_print.PrintJob(order, form, note=note, address=address))
    pdf = form_print.build_forms_pdf(jobs, group_by_form=request.POST.get("group") != "order")
    return _file_response(
        pdf, content_type="application/pdf", ascii_name="forms.pdf",
        quoted_name=quote("套表列印.pdf"), inline=True,
    )


@login_required
@require_POST
def form_print_envelopes(request):
    """信封 Word 檔：沿用原稿 21×17 cm 自訂紙張，用 Word 列印才不會被瀏覽器縮放。"""
    found, error = _picked_orders(request, ("envelope",))
    if error:
        return error
    orders = [order for order, _form in found]
    # 電車信封印出已存的車控密碼，每張訂單留處理紀錄。
    actor = request.user.get_full_name() or request.user.get_username()
    for order in orders:
        if form_print.has_control_password(order):
            OrderEvent.objects.create(order=order, event_type="secret_viewed", description="套表列印電車信封（含車控密碼）", actor_name=actor)
    return _file_response(
        form_print.build_envelopes_docx(orders),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ascii_name="envelopes.docx", quoted_name=quote("信封.docx"), inline=False,
    )
