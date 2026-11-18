"""訂單匯出頁（T-232 第 1 版）。

GET `order_export`：範圍（沿用全部訂單頁的篩選）→ 勾欄位 →（帶 `preview=1`）預覽前 50 列。只讀，不留紀錄。
POST `order_export_download`：使用者在預覽下方按「確認匯出」才產生 xlsx，並寫 `OrderExportRecord`；
含補助撥款帳戶時，每張單比照「查看完整帳號」寫 `payout_account_viewed` 事件。
"""
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import SuspiciousOperation
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from sales.models import OrderEvent, OrderExportRecord

from . import columns as cols
from .scope import export_queryset, scope_labels, scope_params
from .workbook import build_workbook

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _actor(user):
    # 與 views._editing_name 同一寫法（全名，沒有就帳號）。
    return user.get_full_name() or user.get_username()


def _selected_keys(source, granted):
    keys = [key for key in source.getlist("cols") if key in cols.COLUMN_BY_KEY]
    return [column.key for column in cols.resolve(keys, granted)] if keys else []


def _scope_or_error(request, params, finance):
    try:
        return export_queryset(request, params, finance=finance), ""
    except SuspiciousOperation as error:
        return (None, None), str(error)


@login_required
@never_cache
@require_GET
def order_export(request):
    granted = cols.permissions_for(request)
    params = scope_params(request.GET)
    chosen = _selected_keys(request.GET, granted)
    selection = chosen or cols.default_selection(granted)
    selected_columns = cols.resolve(selection, granted)
    (orders, tab), scope_error = _scope_or_error(request, params, "finance" in {c.group for c in selected_columns})
    total = orders.count() if orders is not None else 0
    preview = None
    if request.GET.get("preview") == "1" and chosen and orders is not None:
        rows = [{"order": order, "cells": [
            {"text": cols.display_text(value, column.kind), "column": column}
            for value, column in zip(cols.row_values(order, selected_columns), selected_columns)
        ]} for order in orders[:cols.PREVIEW_ROWS]]
        summary = cols.summary(selected_columns)
        sensitive = [label for key, label in (("pii", "個資"), ("finance", "收支"), ("profit", "淨利")) if summary[key]]
        preview = {"rows": rows, "columns": selected_columns, "summary": summary, "sensitive_label": "、".join(sensitive),
                   "shown": len(rows), "too_many": total > cols.EXPORT_LIMIT}
    back_query = params.copy()
    return render(request, "sales/order_exchange/export.html", {
        "groups": cols.group_rows(granted, set(selection)),
        "scope_labels": scope_labels(params, tab) if orders is not None else [],
        "scope_error": scope_error,
        "scope_items": list(params.lists()),
        "total": total,
        "limit": cols.EXPORT_LIMIT,
        "preview_rows": cols.PREVIEW_ROWS,
        "preview": preview,
        "selected_keys": [column.key for column in selected_columns],
        "order_list_url": f"{reverse('order_list')}?{back_query.urlencode()}" if back_query else reverse("order_list"),
    })


@login_required
@never_cache
@require_POST
def order_export_download(request):
    granted = cols.permissions_for(request)
    params = scope_params(request.POST)
    keys = _selected_keys(request.POST, granted)
    retry = f"{reverse('order_export')}?{params.urlencode()}"
    if not keys:
        messages.error(request, "請先勾選要匯出的欄位並預覽。")
        return redirect(retry)
    selected_columns = cols.resolve(keys, granted)
    summary = cols.summary(selected_columns)
    (orders, tab), scope_error = _scope_or_error(request, params, summary["finance"])
    if scope_error:
        messages.error(request, scope_error)
        return redirect(retry)
    total = orders.count()
    if total == 0:
        messages.error(request, "目前範圍沒有訂單可以匯出。")
        return redirect(retry)
    if total > cols.EXPORT_LIMIT:
        messages.error(request, f"符合的訂單有 {total:,} 張，超過每次 {cols.EXPORT_LIMIT:,} 張的上限，請先縮小範圍。")
        return redirect(retry)

    editable = [(index, column) for index, column in enumerate(selected_columns) if column.editable]
    rows, baseline = [], {}
    for order in orders.iterator(chunk_size=250):
        values = cols.row_values(order, selected_columns)
        rows.append((order.pk, values))
        baseline[str(order.pk)] = {
            "revision": order.revision,
            "values": {column.key: cols.baseline_text(values[index], column.kind) for index, column in editable},
        }
    actor = _actor(request.user)
    with transaction.atomic():
        record = OrderExportRecord.objects.create(
            created_by=request.user if request.user.is_authenticated else None,
            actor_name=actor,
            scope={"params": dict(params.items()), "labels": [list(pair) for pair in scope_labels(params, tab)]},
            columns=[column.key for column in selected_columns],
            row_count=len(rows),
            contains_pii=summary["pii"],
            contains_finance=summary["finance"],
            contains_profit=summary["profit"],
            baseline=baseline,
        )
        if {"bank_name", "remittance_account"} & {column.key for column in selected_columns}:
            OrderEvent.objects.bulk_create([
                OrderEvent(order_id=pk, event_type="payout_account_viewed", actor_name=actor,
                           description="匯出訂單 Excel（含補助撥款帳戶）")
                for pk, _values in rows
            ])
    content = build_workbook(record.token, selected_columns, rows)
    stamp = timezone.localtime(record.created_at).strftime("%Y%m%d-%H%M")
    filename = f"orders-{stamp}.xlsx"
    response = HttpResponse(content, content_type=XLSX)
    response["Content-Disposition"] = (
        f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quote(f"訂單匯出-{stamp}.xlsx")}'
    )
    return response
