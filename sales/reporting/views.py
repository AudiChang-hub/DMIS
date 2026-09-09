import copy
import csv
import hashlib
import json
from functools import wraps
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .engine import DATE_DIMENSIONS, NAVIGATION_GROUPS, card_result, drill_query, scope_labels, validate_config
from .forms import CardFormSet, FilterForm, ReportForm
from .models import ReportDefinition, ReportRevision
from .records import RECORD_COLUMNS, DEFAULT_RECORD_COLUMNS, RECORD_NOTE, record_context, record_queryset, record_cells


def is_editor(user):
    return user.is_authenticated and user.is_active and user.is_superuser and user.get_username() == "admin"


def editor_required(view):
    @wraps(view)
    @login_required
    @never_cache
    def wrapped(request, *args, **kwargs):
        if not is_editor(request.user):
            raise PermissionDenied("只有 admin 可以管理報表設計。")
        return view(request, *args, **kwargs)
    return wrapped


def initial_config():
    return {"title": "銷售台數分析", "description": "依領牌日期探索銷售結構；不含草稿及取消訂單。",
            "audience": "admin", "date_basis": "registration_date", "cards": [
                {"title": "品牌銷售台數", "dimension": "brand", "metric": "count", "chart": "bar", "formula": "", "limit": 20, "sort": "value"},
                {"title": "每月銷售走勢", "dimension": "month", "metric": "count", "chart": "line", "formula": "", "limit": 200, "sort": "key"},
            ]}


def card_filters(filters, index):
    return {**filters, "_card_grain": filters.get(f"grain_{index}"), "_card_sort": filters.get(f"sort_{index}")}


def results(config, filters):
    items = []
    for index, card in enumerate(config["cards"]):
        result = card_result(config, card, card_filters(filters, index))
        result["index"] = index
        result["sort_field"] = f"sort_{index}"
        result["grain_field"] = f"grain_{index}"
        result["selected_sort"] = filters.get(f"sort_{index}", "")
        result["selected_grain"] = filters.get(f"grain_{index}", "")
        result["date_dimension"] = card["dimension"] in DATE_DIMENSIONS
        result["controls_hidden"] = [{"name": key, "value": entry} for key, value in filters.items()
            if value and key not in (f"sort_{index}", f"grain_{index}") and not key.startswith("_")
            for entry in (value if isinstance(value, (list, tuple)) else [value])]
        items.append(result)
    return items


def accessible_report(request, pk):
    report = get_object_or_404(ReportDefinition, pk=pk, published__isnull=False)
    if not request.user.is_active or ((report.published["audience"] != "team" or report.published.get("records_mode") == "population") and not is_editor(request.user)):
        raise Http404
    return report


def publication_key(report):
    return hashlib.sha256(json.dumps(report.published, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def stale_publication(request, report):
    return ((bool(request.GET.get("focus")) and not request.GET.get("revision")) or
            (request.GET.get("revision") and request.GET["revision"] != publication_key(report)))


def filters_for(request, config=None):
    form = FilterForm(request.GET, date_basis=(config or {}).get("date_basis", "registration_date"))
    if not form.is_valid():
        raise ValidationError("；".join(str(error) for errors in form.errors.values() for error in errors))
    return form, form.cleaned_data


def filter_query(filters):
    return urlencode({key: value for key, value in filters.items() if value and not key.startswith("_")}, doseq=True)


def navigation(request):
    reports = ReportDefinition.objects.filter(published__isnull=False)
    if not is_editor(request.user):
        reports = reports.filter(published__audience="team")
    groups = {key: [] for key in NAVIGATION_GROUPS}
    for report in reports:
        groups[report.published.get("navigation_group", "custom")].append(report)
    return [{"label": NAVIGATION_GROUPS[key], "pages": sorted(pages, key=lambda page: (page.published.get("page_order", 0), page.pk))}
            for key, pages in groups.items() if pages]


@login_required
@never_cache
def center(request):
    reports = ReportDefinition.objects.exclude(published=None)
    if not is_editor(request.user):
        reports = reports.filter(published__audience="team")
    return render(request, "sales/reporting/center.html", {"reports": reports})


@editor_required
def manage(request):
    return render(request, "sales/reporting/manage.html", {"reports": ReportDefinition.objects.all()})


@editor_required
def draft_preview(request, pk):
    """只讀取已儲存草稿；不發布、不新增版本，不能由讀者路由存取。"""
    report = get_object_or_404(ReportDefinition, pk=pk)
    config = report.draft
    form = FilterForm(request.GET, date_basis=config["date_basis"])
    items, records, error = [], {}, ""
    if form.is_valid():
        try:
            validate_config(config)
            items = results(config, form.cleaned_data)
            if config.get("include_records"):
                records = record_context(config, form.cleaned_data, request.GET.get("records_page", 1))
        except ValidationError as exc:
            error = "；".join(exc.messages)
    return render(request, "sales/reporting/draft_preview.html", {
        "report": report, "config": config, "filter_form": form, "results": items,
        "scope_labels": scope_labels(config.get("fixed_filters", {})), "error": error,
        "query": filter_query(form.cleaned_data) if form.is_valid() else "", **records,
        "is_preview": True, "standalone_preview": True,
        "draft_reports": sorted(ReportDefinition.objects.all(), key=lambda row: (row.draft.get("page_order", 0), row.pk)),
    })


@editor_required
def edit(request, pk=None):
    report = get_object_or_404(ReportDefinition, pk=pk) if pk else None
    config = report.draft if report else initial_config()
    form = ReportForm(request.POST or None, initial={**config, "version": report.version if report else 0})
    formset = CardFormSet(request.POST or None, initial=config["cards"], prefix="cards")
    preview = None
    preview_records = {}
    status = 200
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        config = {key: form.cleaned_data[key] for key in ("title", "description", "audience", "date_basis", "navigation_group", "page_order", "include_undated", "include_records", "records_columns", "records_page_size", "records_mode")}
        config["fixed_filters"] = form.scope_data()
        config["cards"] = [{**{key: card.cleaned_data[key] for key in ("title", "dimension", "metric", "chart", "formula", "limit", "sort", "series", "series_limit", "series_other", "series_sort", "additional_metrics", "width", "height")}, "fixed_filters": card.scope_data()}
                           for card in formset.ordered_forms]
        action = request.POST.get("action")
        try:
            validate_config(config)
            if action == "canvas":
                items = results(config, {})
                return JsonResponse({"cards": [render_to_string("sales/reporting/canvas_frame.html", {"result": item, "is_preview": True}, request=request) for item in items]})
            elif action == "preview":
                preview = results(config, {})
                if config.get("include_records"):
                    preview_records = record_context(config, {})
            elif action in ("save", "publish"):
                with transaction.atomic():
                    if report:
                        report = ReportDefinition.objects.select_for_update().get(pk=report.pk)
                        if report.version != form.cleaned_data["version"]:
                            raise ValidationError("此報表已由另一個分頁更新。本頁輸入仍保留，請另開管理頁確認最新版本，避免覆蓋。")
                    else:
                        if form.cleaned_data["version"] != 0:
                            raise ValidationError("新報表版本不正確。")
                        report = ReportDefinition()
                    report.draft = config
                    report.version += 1
                    if action == "publish":
                        # 發布前實際執行，無效或超限的公式不進入讀者版本。
                        results(config, {})
                        if config.get("include_records"):
                            record_context(config, {})
                        report.published = copy.deepcopy(config)
                        report.published_at = timezone.now()
                    report.save()
                    ReportRevision.objects.create(report=report, version=report.version, action=action, config=config, actor=request.user)
                messages.success(request, "報表已發布。" if action == "publish" else "草稿已儲存，已發布版本不受影響。")
                return redirect("report_edit", pk=report.pk)
            else:
                raise ValidationError("請使用儲存草稿、預覽或發布按鈕。")
        except ValidationError as error:
            form.add_error(None, error)
            status = 400
    if request.method == "POST" and request.POST.get("action") == "canvas":
        return JsonResponse({"errors": {"report": form.errors.get_json_data(), "cards": formset.errors, "formset": list(formset.non_form_errors())}}, status=400)
    rendered_cards = [*formset.ordered_forms, *formset.deleted_forms] if formset.is_bound and formset.is_valid() else formset
    return render(request, "sales/reporting/edit.html", {"report": report, "form": form, "formset": formset, "rendered_cards": rendered_cards,
                  "preview": preview, "is_preview": True, **preview_records, "revisions": report.revisions.all()[:20] if report else []}, status=status)


@editor_required
@require_POST
def lifecycle(request, pk):
    with transaction.atomic():
        report = get_object_or_404(ReportDefinition.objects.select_for_update(), pk=pk)
        if str(report.version) != request.POST.get("version"):
            return HttpResponse("報表已更新，請重新整理後再操作。", status=409)
        action = request.POST.get("action")
        if action == "duplicate":
            config = copy.deepcopy(report.draft)
            config["title"] = config["title"][:94] + "（複本）"
            config["audience"] = "admin"
            duplicate = ReportDefinition.objects.create(draft=config, version=1)
            ReportRevision.objects.create(report=duplicate, version=1, action="duplicate", config=config, actor=request.user)
            return redirect("report_edit", pk=duplicate.pk)
        if action == "unpublish":
            report.published = None
            report.published_at = None
        elif action == "restore":
            raw_revision = request.POST.get("revision", "")
            if not raw_revision.isascii() or not raw_revision.isdigit() or len(raw_revision) > 9:
                return HttpResponse("版本編號不正確。", status=400)
            revision = get_object_or_404(report.revisions, version=int(raw_revision))
            report.draft = copy.deepcopy(revision.config)
        else:
            return HttpResponse("不支援此操作。", status=400)
        report.version += 1
        report.save()
        ReportRevision.objects.create(report=report, version=report.version, action=action, config=report.draft, actor=request.user)
    messages.success(request, "已取消發布，讀者不再能開啟。" if action == "unpublish" else "已還原為草稿，檢查後再發布。")
    return redirect("report_edit", pk=pk)


@login_required
@never_cache
def display(request, pk):
    report = accessible_report(request, pk)
    if (request.GET.get("records_page") or request.GET.get("focus")) and stale_publication(request, report):
        return render(request, "sales/reporting/stale.html", {"report": report}, status=409)
    form = FilterForm(request.GET, date_basis=report.published["date_basis"])
    items = []
    records = {}
    error = ""
    if form.is_valid():
        try:
            items = results(report.published, form.cleaned_data)
            if report.published.get("include_records"):
                records = record_context(report.published, form.cleaned_data, request.GET.get("records_page", 1))
        except ValidationError as exc:
            error = "；".join(exc.messages)
    query = filter_query(form.cleaned_data) if form.is_valid() else ""
    focus_items = []
    if form.is_valid():
        from .cross_filter import selections, selection_label
        chosen = selections(form.cleaned_data.get("focus"))
        for item in chosen:
            if item["card"] < len(report.published["cards"]):
                remaining = [value for value in chosen if value != item]
                clear_filters = {**form.cleaned_data, "focus": json.dumps(remaining) if remaining else ""}
                focus_items.append({"title": report.published["cards"][item["card"]]["title"] + "：" + selection_label(report.published, item),
                    "remove_query": filter_query(clear_filters) + "&revision=" + publication_key(report)})
    query += ("&" if query else "") + urlencode({"revision": publication_key(report)})
    return render(request, "sales/reporting/display.html", {"report": report, "config": report.published,
                  "navigation": navigation(request), "scope_labels": scope_labels(report.published.get("fixed_filters", {})),
                  "filter_form": form, "results": items, **records, "query": query, "error": error, "queried_at": timezone.now(),
                  "publication_key": publication_key(report), "focus_items": focus_items})


@login_required
@never_cache
def records_export(request, pk):
    report = accessible_report(request, pk)
    if not report.published.get("include_records"):
        raise Http404
    if stale_publication(request, report):
        return render(request, "sales/reporting/stale.html", {"report": report}, status=409)
    try:
        _, filters = filters_for(request, report.published)
    except ValidationError as error:
        return HttpResponse("；".join(error.messages), status=400, content_type="text/plain; charset=utf-8")
    grouped = report.published.get("records_mode") == "population"
    if grouped:
        from .population_table import population_queryset, population_cells, HEADERS, NOTE
        # 發布設定被異常改寫時，也不能透過匯出繞過 admin 限制。
        if not is_editor(request.user):
            raise Http404
        queryset = population_queryset(report.published, filters)
    else:
        queryset = record_queryset(report.published, filters)
    if queryset.count() > 5000:
        return HttpResponse("明細超過 5000 筆，請縮小篩選範圍後匯出。", status=400)
    columns = report.published.get("records_columns", DEFAULT_RECORD_COLUMNS)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="report-{pk}-orders.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["報表", csv_safe(report.published["title"]), "篩選", csv_safe(filter_query(filters))])
    writer.writerow(["報表固定範圍", csv_safe("；".join(scope_labels(report.published.get("fixed_filters", {}))) or "不限")])
    writer.writerow(["口徑", NOTE if grouped else RECORD_NOTE])
    writer.writerow(HEADERS if grouped else [RECORD_COLUMNS[key] for key in columns])
    for order in queryset.iterator(chunk_size=250):
        values = population_cells(order) if grouped else [cell["value"] for cell in record_cells(order, columns)]
        writer.writerow([csv_safe(value) for value in values])
    return response


def selected_card(config, index):
    if index < 0 or index >= len(config["cards"]):
        raise Http404
    return config["cards"][index]


@login_required
@never_cache
def detail(request, pk, index):
    report = accessible_report(request, pk)
    if stale_publication(request, report):
        return render(request, "sales/reporting/stale.html", {"report": report}, status=409)
    card = selected_card(report.published, index)
    try:
        _, filters = filters_for(request, report.published)
        queryset = drill_query(report.published, card, card_filters(filters, index), request.GET.get("group", "__all__"))
    except ValidationError as error:
        return HttpResponse("；".join(error.messages), status=400, content_type="text/plain; charset=utf-8")
    page = Paginator(queryset.select_related("vehicle_model", "source", "commission_recipient", "operations").order_by("-order_date", "-pk"), 50).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    template = "sales/reporting/detail_panel.html" if request.GET.get("inline") == "1" else "sales/reporting/detail.html"
    return render(request, template, {"report": report, "card": card, "page_obj": page,
                  "scope_labels": scope_labels(report.published.get("fixed_filters", {})) + scope_labels(card.get("fixed_filters", {})),
                  "query": query.urlencode(), "back_query": filter_query(filters)})


def csv_safe(value):
    text = str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else text


@login_required
@never_cache
def export(request, pk, index):
    report = accessible_report(request, pk)
    if stale_publication(request, report):
        return render(request, "sales/reporting/stale.html", {"report": report}, status=409)
    card = selected_card(report.published, index)
    try:
        _, filters = filters_for(request, report.published)
        result = card_result(report.published, card, card_filters(filters, index))
    except ValidationError as error:
        return HttpResponse("；".join(error.messages), status=400, content_type="text/plain; charset=utf-8")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="report-{pk}-chart-{index}.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["報表", csv_safe(report.published["title"]), "圖表", csv_safe(card["title"])])
    writer.writerow(["日期依據", report.published["date_basis"], "篩選", csv_safe(filter_query(filters))])
    writer.writerow(["報表固定範圍", csv_safe("；".join(scope_labels(report.published.get("fixed_filters", {}))) or "不限")])
    writer.writerow(["圖表固定範圍", csv_safe("；".join(result["scope_labels"]) or "沿用報表範圍")])
    writer.writerow(["統計範圍", "不含草稿與取消訂單；車價不是實收／淨利"])
    if result.get("financial_note"):
        writer.writerow(["財務口徑", result["financial_note"]])
    if result.get("compatibility_note"):
        writer.writerow(["分類口徑", result["compatibility_note"]])
    writer.writerow(["公式", csv_safe(card["formula"] if card["metric"] == "formula" else card["metric"])])
    writer.writerow(["未填日期", "未選期間時納入，另列未填日期" if report.published.get("include_undated") else "領牌日期基準時排除"])
    if result.get("summary_table"):
        writer.writerow([*result["table_dimension_labels"], *result["table_metric_labels"]])
        for row in result["rows"]:
            writer.writerow([*[csv_safe(value) for value in row["dimension_cells"]],
                             *[cell["value"] if cell["value"] is not None else cell["display"] for cell in row["metric_cells"]]])
    elif card["chart"] == "stacked":
        writer.writerow([result["dimension_label"], result["series_label"], result["metric_label"], "訂單台數"])
        for row in result["rows"]:
            for segment in row["segments"]:
                writer.writerow([csv_safe(row["label"]), csv_safe(segment["label"]), segment["value"], segment["count"]])
    else:
        writer.writerow([result["dimension_label"], result["metric_label"], "訂單台數"])
        for row in result["rows"]:
            writer.writerow([csv_safe(row["label"]), row["value"] if row["value"] is not None else row["display"], row["count"]])
    if result["truncated"]:
        writer.writerow(["提醒", "僅匯出目前圖表顯示群組，非全部群組"])
    if result["series_truncated"]:
        writer.writerow(["細分系列", "其餘合併為其他" if card.get("series_other") else "未顯示系列未匯出；完整彙總仍包含"])
    return response
