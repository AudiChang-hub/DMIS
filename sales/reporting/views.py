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
from .records import RECORD_COLUMNS, DEFAULT_RECORD_COLUMNS, RECORD_NOTE, record_context, record_queryset, record_cells, visible_record_columns


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


def results(config, filters, *, retain_candidates=False):
    items = []
    for index, card in enumerate(config["cards"]):
        visual_filters = filters
        if retain_candidates and filters.get("focus"):
            from .cross_filter import selections
            chosen = selections(filters["focus"])
            remaining = [item for item in chosen if item["card"] != index]
            if len(remaining) != len(chosen):
                visual_filters = {**filters, "focus": json.dumps(remaining)}
        result = card_result(config, card, card_filters(visual_filters, index))
        result["retained_candidates"] = visual_filters is not filters
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
    if hasattr(request, "_designer_report"):
        if not is_editor(request.user) or request._designer_report.pk != pk:
            raise PermissionDenied
        return request._designer_report
    report = get_object_or_404(ReportDefinition, pk=pk, published__isnull=False)
    from sales.access.services import policy_for
    if not policy_for(request).report(report):
        raise Http404
    return report


def publication_key(report):
    from .classification import published_snapshot
    classification_version = published_snapshot()[1]
    return hashlib.sha256(json.dumps([report.published, classification_version], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def stale_publication(request, report):
    return ((bool(request.GET.get("focus")) and not request.GET.get("revision")) or
            (request.GET.get("revision") and request.GET["revision"] != publication_key(report)))


def filters_for(request, config=None):
    form = FilterForm(request.GET, date_basis=(config or {}).get("date_basis", "registration_date"), config=config)
    if not form.is_valid():
        raise ValidationError("；".join(str(error) for errors in form.errors.values() for error in errors))
    return form, form.cleaned_data


def filter_query(filters):
    return urlencode({key: value for key, value in filters.items() if value and not key.startswith("_")}, doseq=True)


def navigation(request):
    if not request.user.is_active:
        return []
    reports = ReportDefinition.objects.filter(published__isnull=False)
    groups = {key: [] for key in NAVIGATION_GROUPS}
    for report in reports:
        from sales.access.services import policy_for
        if not policy_for(request).report(report):
            continue
        report.reader_title = reader_title(report.published)
        groups[report.published.get("navigation_group", "custom")].append(report)
    return [{"label": NAVIGATION_GROUPS[key], "pages": sorted(pages, key=lambda page: (page.published.get("page_order", 0), page.pk))}
            for key, pages in groups.items() if pages]


def reader_title(config):
    return config["title"].replace("｜原報表核對版", "").replace("原報表核對版", "").rstrip(" ｜|")


@login_required
@never_cache
def center(request):
    pages = [report for group in navigation(request) for report in group["pages"]]
    if not pages:
        request.session.pop("report_reader_page", None)
        return render(request, "sales/reporting/center.html")
    remembered = request.session.get("report_reader_page", {})
    if not isinstance(remembered, dict) or remembered.get("user") != str(request.user.pk):
        remembered = {}
    selected = next((page for page in pages if page.pk == remembered.get("report")), pages[0])
    return display(request, selected.pk)


@editor_required
def manage(request):
    return render(request, "sales/reporting/manage.html", {"reports": ReportDefinition.objects.all()})


@editor_required
def draft_preview(request, pk):
    """只讀取已儲存草稿；不發布、不新增版本，不能由讀者路由存取。"""
    report = get_object_or_404(ReportDefinition, pk=pk)
    config = report.draft
    form = FilterForm(request.GET, date_basis=config["date_basis"], config=config)
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
        config = {key: form.cleaned_data[key] for key in ("reader_layout", "title", "description", "audience", "date_basis", "navigation_group", "page_order", "include_undated", "include_records", "records_columns", "records_page_size", "records_mode")}
        config["fixed_filters"] = form.scope_data()
        config["cards"] = [{**{key: card.cleaned_data[key] for key in ("title", "dimension", "metric", "chart", "formula", "limit", "sort", "series", "series_limit", "series_other", "series_sort", "additional_metrics", "width", "height", "font_size", "title_align", "palette", "show_legend", "show_tooltip", "cross_filter")}, "fixed_filters": card.scope_data()}
                           for card in formset.ordered_forms]
        action = request.POST.get("action")
        try:
            validate_config(config)
            if action == "canvas":
                from .designer import preview_response
                response = preview_response(request, report, config)
                return JsonResponse({"document": response.content.decode(), "status": response.status_code,
                                     "content_type": response.get("Content-Type", "text/html")})
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
    designer_pages = sorted(ReportDefinition.objects.all(), key=lambda row: (list(NAVIGATION_GROUPS).index(row.draft.get("navigation_group", "custom")), row.draft.get("page_order", 0), row.pk))
    for page in designer_pages:
        page.reader_title = reader_title(page.draft)
    return render(request, "sales/reporting/edit.html", {"report": report, "form": form, "formset": formset, "rendered_cards": rendered_cards,
                  "designer_pages": designer_pages,
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
            report.draft["title"] = reader_title(report.draft)
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
    form = FilterForm(request.GET, date_basis=report.published["date_basis"], reader_layout=report.published.get("reader_layout", "standard"), config=report.published)
    items = []
    records = {}
    error = ""
    if form.is_valid():
        try:
            items = results(report.published, form.cleaned_data, retain_candidates=True)
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
    remembered = {"user": str(request.user.pk), "report": report.pk}
    if not hasattr(request, "_designer_report") and request.session.get("report_reader_page") != remembered:
        request.session["report_reader_page"] = remembered
    return render(request, "sales/reporting/display.html", {"report": report, "config": report.published,
                  "reader_title": reader_title(report.published),
                  "reader_overview": report.published.get('reader_layout', 'standard') != 'standard',
                  "navigation": navigation(request), "scope_labels": scope_labels(report.published.get("fixed_filters", {})),
                  "filter_form": form, "results": items, **records, "query": query, "error": error, "queried_at": timezone.now(),
                  "publication_key": publication_key(report), "focus_items": focus_items,
                  "can_edit_report": is_editor(request.user) and not hasattr(request, "_designer_report"),
                  "designer_frame": hasattr(request, "_designer_report"),
                  "report_base": "sales/reporting/designer_frame.html" if hasattr(request, "_designer_report") else "sales/reporting/layout.html",
                  "preview_boot": {"channel": getattr(request, "_designer_channel", ""),
                                   "url": request.build_absolute_uri(request.path + "?" + query)}})


@login_required
@never_cache
def records_export(request, pk):
    report = accessible_report(request, pk)
    from sales.access.services import policy_for
    if not policy_for(request).report(report, "export"):
        raise PermissionDenied
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
        # accessible_report 與上方 export 檢核均已套用逐份授權。
        queryset = population_queryset(report.published, filters)
    else:
        queryset = record_queryset(report.published, filters)
    if queryset.count() > 5000:
        return HttpResponse("明細超過 5000 筆，請縮小篩選範圍後匯出。", status=400)
    columns = visible_record_columns(report.published)
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
    from sales.access.services import policy_for
    if not policy_for(request).report(report, "export"):
        raise PermissionDenied
    if stale_publication(request, report):
        return render(request, "sales/reporting/stale.html", {"report": report}, status=409)
    card = selected_card(report.published, index)
    try:
        _, filters = filters_for(request, report.published)
        result = card_result(report.published, card, card_filters(filters, index))
    except ValidationError as error:
        return HttpResponse("；".join(error.messages), status=400, content_type="text/plain; charset=utf-8")
    export_format = request.GET.get('format', 'excel')
    if export_format not in ('csv', 'excel') or request.GET.get('formatted', '0') not in ('0', '1'):
        return HttpResponse('不支援的匯出格式。', status=400)
    formatted = request.GET.get('formatted') == '1'
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="report-{pk}-chart-{index}.csv"'
    if export_format == 'excel':
        response.write("\ufeff")
    writer = csv.writer(response)
    # 原入口保留稽核說明；新明確格式輸出矩形資料，方便匯入試算表。
    include_notes = 'format' not in request.GET
    if include_notes:
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
        include_count = include_notes or card['metric'] != 'count'
        writer.writerow([result["dimension_label"], result["series_label"], result["metric_label"], *(['訂單台數'] if include_count else [])])
        for row in result["rows"]:
            for segment in row["segments"]:
                writer.writerow([csv_safe(row["label"]), csv_safe(segment["label"]), segment["display"] if formatted else segment["value"], *([segment['count']] if include_count else [])])
    else:
        include_count = include_notes or card['metric'] != 'count'
        writer.writerow([result["dimension_label"], result["metric_label"], *(['訂單台數'] if include_count else [])])
        for row in result["rows"]:
            writer.writerow([csv_safe(row["label"]), row["display"] if formatted or row["value"] is None else row["value"], *([row['count']] if include_count else [])])
    if include_notes and result["truncated"]:
        writer.writerow(["提醒", "僅匯出目前圖表顯示群組，非全部群組"])
    if include_notes and result["series_truncated"]:
        writer.writerow(["細分系列", "其餘合併為其他" if card.get("series_other") else "未顯示系列未匯出；完整彙總仍包含"])
    return response
