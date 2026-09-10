"""已驗證 admin 表單的無狀態、唯讀預覽；不暫存或發布使用者設定。"""
import copy
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.http import QueryDict
from django.urls import Resolver404, resolve, reverse

from .models import ReportDefinition


def preview_response(request, report, config):
    from . import views

    pk = report.pk if report else 0
    target = request.POST.get("preview_url") or reverse("report_display", args=[pk])
    if len(target) > 16000:
        raise ValidationError("預覽篩選過長，請縮小選取範圍。")
    try:
        url = urlsplit(target)
    except ValueError as exc:
        raise ValidationError("預覽網址格式不正確。") from exc
    if url.scheme or url.netloc or not url.path.startswith("/reports/"):
        raise ValidationError("預覽僅允許查詢本報表，不接受外部網址。")
    try:
        match = resolve(url.path)
    except Resolver404 as exc:
        raise ValidationError("不支援的預覽操作。") from exc
    handlers = {
        "report_display": views.display, "report_detail": views.detail,
        "report_export": views.export, "report_records_export": views.records_export,
    }
    if match.url_name not in handlers or match.kwargs.get("pk") != pk:
        raise ValidationError("預覽僅允許查詢目前設計的報表。")
    preview_request = copy.copy(request)
    preview_request.method = "GET"
    preview_request.GET = QueryDict(url.query)
    preview_request._designer_report = ReportDefinition(pk=pk, draft=config, published=config)
    preview_request._designer_channel = request.POST.get("preview_channel", "")[:100]
    preview_request.GET = preview_request.GET.copy()
    preview_request.GET["revision"] = views.publication_key(preview_request._designer_report)
    preview_request.path = url.path
    return handlers[match.url_name](preview_request, **match.kwargs)
