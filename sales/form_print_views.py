"""套表列印：一次勾選多張訂單、每張各自要印的套表，輸出成一份 PDF。"""
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import FileResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from sales.models import OrderEvent, SalesOrder
from sales.services import form_print, order_tabs
from sales.services.order_intake import is_dealer, scoped_orders
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
    if is_dealer(request.user):
        raise PermissionDenied
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


@login_required
@require_POST
def form_print_pdf(request):
    if is_dealer(request.user):
        raise PermissionDenied
    picked = _parse_jobs(request)
    if not picked:
        messages.error(request, "請至少勾選一張訂單的一份套表。")
        return redirect("form_print")
    if len(picked) > MAX_JOBS:
        messages.error(request, f"一次最多列印 {MAX_JOBS} 份，請分批列印。")
        return redirect("form_print")
    orders = _orders(request.user).in_bulk({pk for pk, _form in picked})
    jobs = []
    for pk, form in picked:
        order = orders.get(pk)
        if order is None:  # 不在權限範圍或已刪除：略過，不透露是否存在。
            continue
        note = address = ""
        if form == "receipt":
            note = request.POST.get(f"note_{pk}", "").strip()[: form_print.NOTE_MAX_CHARS]
            address = request.POST.get(f"address_{pk}", "").strip()[: form_print.ADDRESS_MAX_CHARS]
        jobs.append(form_print.PrintJob(order, form, note=note, address=address))
    if not jobs:
        messages.error(request, "勾選的訂單已不存在或沒有權限列印。")
        return redirect("form_print")
    # 電車信封印出已存的車控密碼，每張訂單留處理紀錄。
    secret_orders = {job.order.pk: job.order for job in jobs if job.form == "envelope" and form_print.has_control_password(job.order)}
    if secret_orders:
        actor = request.user.get_full_name() or request.user.get_username()
        for order in secret_orders.values():
            OrderEvent.objects.create(order=order, event_type="secret_viewed", description="套表列印電車信封（含車控密碼）", actor_name=actor)
    pdf = form_print.build_forms_pdf(
        jobs, group_by_form=request.POST.get("group") != "order", reveal_secrets=bool(secret_orders),
    )
    response = FileResponse(BytesIO(pdf), content_type="application/pdf")
    response["Content-Disposition"] = (
        "inline; filename=\"forms.pdf\"; filename*=UTF-8''%E5%A5%97%E8%A1%A8%E5%88%97%E5%8D%B0.pdf"
    )
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    return response
