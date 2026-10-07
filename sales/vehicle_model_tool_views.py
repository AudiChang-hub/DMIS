"""機種與售價的批次工具：沿用建立（新生效日／新年式）與批次調整。

所有寫入都先預覽、再以簽章後的預覽內容送出；只建立新版本，不修改既有版本。
"""
from datetime import date
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods

from sales.access.services import policy_for
from sales.models import VehicleModel
from sales.services import vehicle_model_batch as batch
from sales.services import vehicle_model_copy as copy_service

COPY_SALT = "vehicle-model-copy"
BATCH_SALT = "vehicle-model-batch"
TOKEN_MAX_AGE = 6 * 60 * 60


def _parse_day(raw):
    try:
        return parse_date((raw or "").strip())
    except ValueError:
        return None


def _filter_query(filters):
    return {key: value for key, value in filters.items() if value not in (None, "")}


def _ids(raw_values):
    ids = []
    for raw in raw_values:
        for part in str(raw).split(","):
            part = part.strip()
            if part.isdigit() and int(part) not in ids:
                ids.append(int(part))
    return ids


def _listed_models(request, filters):
    """POST 時沿用畫面上列出的年式；GET 時依指定年式或篩選條件。回傳 (年式, 是否超過上限, 指定 ids)。"""
    source = request.POST if request.method == "POST" else request.GET
    if request.method == "POST":
        ids = _ids(source.getlist("row"))
        models = VehicleModel.objects.select_related("family").filter(pk__in=ids).order_by(*copy_service.MODEL_ORDER)
        return list(models), False, _ids(source.getlist("ids"))
    ids = _ids(source.getlist("ids"))
    if ids:
        models = VehicleModel.objects.select_related("family").filter(pk__in=ids).order_by(*copy_service.MODEL_ORDER)
        return list(models), False, ids
    models = list(copy_service.filtered_models(filters)[: batch.MAX_ROWS + 1])
    return models[: batch.MAX_ROWS], len(models) > batch.MAX_ROWS, []


def _dataset_choices(allowed, keys, labels, hints):
    return [
        {"key": key, "label": labels[key], "hint": hints.get(key, ""), "allowed": allowed.get(key, False)}
        for key in keys
    ]


# ---------------------------------------------------------------------------
# 沿用建立
# ---------------------------------------------------------------------------

@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def vehicle_model_copy(request):
    policy = policy_for(request)
    today = timezone.localdate()
    source = request.POST if request.method == "POST" else request.GET
    mode = "year" if source.get("mode") == "year" else "date"
    action = request.POST.get("action", "") if request.method == "POST" else ""

    if action == "commit":
        return _copy_commit(request, policy)

    filters = copy_service.read_filters(source)
    allowed = copy_service.allowed_datasets(policy, include_extras=True)
    state = {
        "effective_from": copy_service.default_effective_from(today),
        "datasets": [key for key in copy_service.VERSIONED_KEYS if allowed[key]],
        "extras": [key for key in copy_service.YEAR_EXTRA_KEYS if allowed[key]],
        "activate": False,
        "selected": set(),
        "years": {},
    }
    errors = []
    if action == "back":
        payload = _load_token(request.POST.get("token"), COPY_SALT)
        if payload:
            mode = payload["mode"]
            state["effective_from"] = date.fromisoformat(payload["date"])
            state["datasets"] = payload["datasets"]
            state["extras"] = payload.get("extras", [])
            state["activate"] = payload.get("activate", False)
            if mode == "year":
                state["selected"] = {pk for pk, _year in payload["entries"]}
                state["years"] = {pk: year for pk, year in payload["entries"]}
            else:
                state["selected"] = set(payload["ids"])
    elif request.method == "POST":
        state["effective_from"] = _parse_day(request.POST.get("effective_from"))
        state["datasets"] = [key for key in request.POST.getlist("datasets") if key in copy_service.VERSIONED_KEYS]
        state["extras"] = [key for key in request.POST.getlist("extras") if key in copy_service.YEAR_EXTRA_KEYS]
        state["activate"] = request.POST.get("activate") == "1"
        state["selected"] = set(_ids(request.POST.getlist("selected")))
        for raw_pk in request.POST.getlist("row"):
            raw_year = (request.POST.get(f"year_{raw_pk}") or "").strip()
            if raw_pk.isdigit() and f"year_{raw_pk}" in request.POST:
                # 格式不對時保留空值，預覽會標示「請填寫新年式」，不默默改回預設年份。
                state["years"][int(raw_pk)] = int(raw_year) if raw_year.isdigit() else None
    elif source.getlist("ids"):
        # 從機種工作區或清單進入時，預先勾選指定的年式。
        state["selected"] = set(_ids(source.getlist("ids")))

    models, truncated, fixed_ids = _listed_models(request, filters)
    for model in models:
        state["years"].setdefault(model.pk, (model.model_year or today.year) + 1)

    if action == "preview":
        errors = _copy_validate(state, mode, allowed, models)
        if not errors:
            return _copy_preview(request, mode, state, models, filters, fixed_ids)

    result = request.session.pop("vehicle_model_copy_result", None) if request.GET.get("result") else None
    rows = [
        {"model": model, "label": copy_service.model_label(model), "selected": model.pk in state["selected"],
         "target_year": state["years"].get(model.pk)}
        for model in models
    ]
    presence_day = _annotate_presence(rows, state["effective_from"] or copy_service.default_effective_from(today), mode)
    return render(request, "sales/vehicle_model_copy.html", {
        "stage": "result" if result else "select",
        "result": result,
        "mode": mode,
        "rows": rows,
        "truncated": truncated,
        "fixed_ids": fixed_ids,
        "filters": filters,
        "filter_options": copy_service.filter_options(),
        "filter_query": urlencode(_filter_query(filters)),
        "datasets": _dataset_choices(allowed, copy_service.VERSIONED_KEYS, copy_service.VERSIONED_LABELS,
                                     copy_service.VERSIONED_HINTS),
        "extras": _dataset_choices(allowed, copy_service.YEAR_EXTRA_KEYS, copy_service.YEAR_EXTRA_LABELS,
                                   copy_service.YEAR_EXTRA_HINTS),
        "state": state,
        "errors": errors,
        "today": today,
        "max_rows": batch.MAX_ROWS,
        "presence_day": presence_day,
    })


def _annotate_presence(rows, day, mode):
    """在選擇清單上顯示每個年式在該日是否有各項版本，方便判斷要不要沿用。"""
    probe = day if mode == "year" else day - copy_service.timedelta(days=1)
    ids = [row["model"].pk for row in rows]
    found = {key: copy_service.current_versions_bulk(key, ids, probe) for key in copy_service.VERSIONED_KEYS}
    for row in rows:
        row["presence"] = [
            {"key": key, "label": copy_service.VERSIONED_LABELS[key], "present": row["model"].pk in found[key]}
            for key in copy_service.VERSIONED_KEYS
        ]
    return probe


def _copy_validate(state, mode, allowed, models):
    errors = []
    try:
        copy_service.validate_effective_from(state["effective_from"])
    except ValidationError as exc:
        errors.extend(exc.messages)
    if any(not allowed.get(key) for key in state["datasets"] + (state["extras"] if mode == "year" else [])):
        errors.append("你沒有其中部分資料的操作權限，請取消勾選後再預覽。")
    if mode == "date" and not state["datasets"]:
        errors.append("請至少勾選一項要沿用的資料。")
    listed = {model.pk for model in models}
    if not state["selected"] & listed:
        errors.append("請至少勾選一個年式。")
    return errors


def _copy_preview(request, mode, state, models, filters, fixed_ids):
    chosen = [model for model in models if model.pk in state["selected"]]
    day = state["effective_from"]
    if mode == "year":
        entries = [(model, state["years"].get(model.pk)) for model in chosen]
        plan = copy_service.plan_new_year(entries, day, state["datasets"], state["extras"])
        payload = {"mode": "year", "date": day.isoformat(), "datasets": state["datasets"], "extras": state["extras"],
                   "activate": state["activate"], "entries": [[model.pk, year] for model, year in entries]}
        blocked = [row for row in plan if row["conflict"]]
        create_total = sum(1 for row in plan if not row["conflict"])
    else:
        plan = copy_service.plan_new_date(chosen, day, state["datasets"])
        payload = {"mode": "date", "date": day.isoformat(), "datasets": state["datasets"],
                   "ids": [model.pk for model in chosen]}
        blocked = []
        create_total = sum(row["create_count"] for row in plan)
    skipped = sum(1 for row in plan for item in row["items"] if item["status"] != "create")
    return render(request, "sales/vehicle_model_copy.html", {
        "stage": "preview",
        "mode": mode,
        "plan": plan,
        "state": state,
        "blocked": blocked,
        "create_total": create_total,
        "skipped_total": skipped,
        "token": signing.dumps(payload, salt=COPY_SALT),
        "dataset_labels": [copy_service.VERSIONED_LABELS[key] for key in state["datasets"]],
        "extra_labels": [copy_service.YEAR_EXTRA_LABELS[key] for key in state["extras"]],
        "listed_ids": [model.pk for model in models],
        "fixed_ids": fixed_ids,
        "filters": filters,
    })


def _load_token(token, salt):
    try:
        return signing.loads(token or "", salt=salt, max_age=TOKEN_MAX_AGE)
    except signing.BadSignature:
        return None


def _copy_commit(request, policy):
    payload = _load_token(request.POST.get("token"), COPY_SALT)
    back_url = reverse("vehicle_model_copy")
    if not payload:
        messages.error(request, "預覽已過期或內容不完整，資料尚未寫入；請重新選擇並預覽。")
        return redirect(back_url)
    mode = payload["mode"]
    allowed = copy_service.allowed_datasets(policy, include_extras=True)
    requested = payload["datasets"] + (payload.get("extras", []) if mode == "year" else [])
    if any(not allowed.get(key) for key in requested):
        messages.error(request, "你沒有其中部分資料的操作權限，資料尚未寫入。")
        return redirect(f"{back_url}?mode={mode}")
    day = date.fromisoformat(payload["date"])
    try:
        if mode == "year":
            rows = copy_service.execute_new_year(
                entries=[(pk, year) for pk, year in payload["entries"]], effective_from=day,
                datasets=payload["datasets"], extras=payload.get("extras", []),
                activate=payload.get("activate", False), actor=request.user,
            )
        else:
            rows, _created = copy_service.execute_new_date(
                model_ids=payload["ids"], effective_from=day, datasets=payload["datasets"], actor=request.user,
            )
    except (ValidationError, IntegrityError) as exc:
        detail = "；".join(exc.messages) if isinstance(exc, ValidationError) else "資料剛被其他人變更"
        messages.error(request, f"沿用未完成，未寫入任何資料：{detail}")
        query = {"mode": mode, "ids": ",".join(str(pk) for pk in (
            [pk for pk, _year in payload["entries"]] if mode == "year" else payload["ids"]))}
        return redirect(f"{back_url}?{urlencode(query)}")
    request.session["vehicle_model_copy_result"] = _copy_result_summary(mode, day, rows, payload)
    created = sum(1 for row in rows for item in row["items"] if item.get("created_id"))
    if mode == "year":
        messages.success(request, f"已建立 {len(rows)} 個新年式、{created} 筆版本。")
    else:
        messages.success(request, f"已建立 {created} 筆 {day:%Y/%m/%d} 起生效的新版本。")
    return redirect(f"{back_url}?mode={mode}&result=1")


def _copy_result_summary(mode, day, rows, payload):
    summary_rows = []
    for row in rows:
        target = row.get("new_model") or row["model"]
        items = [
            {"label": item["label"], "created": bool(item.get("created_id")), "reason": item["reason"],
             "url": reverse(copy_service.VERSIONED_ROUTES[item["dataset"]], args=[target.pk])
             if item.get("created_id") else ""}
            for item in row["items"]
        ]
        summary_rows.append({
            "label": copy_service.model_label(target) if mode == "year" else row["label"],
            "base_label": row["label"],
            "url": reverse("vehicle_model_edit", args=[target.pk]),
            "items": items,
            "extras": [extra["label"] for extra in row.get("extras", []) if extra["status"] == "create"],
            "created": sum(item["created"] for item in items),
        })
    return {
        "mode": mode,
        "date": day.strftime("%Y/%m/%d"),
        "activate": payload.get("activate", False),
        "rows": summary_rows,
        "created_total": sum(row["created"] for row in summary_rows),
        "skipped_total": sum(1 for row in summary_rows for item in row["items"] if not item["created"]),
    }


# ---------------------------------------------------------------------------
# 批次調整
# ---------------------------------------------------------------------------

@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def vehicle_model_batch(request):
    policy = policy_for(request)
    today = timezone.localdate()
    source = request.POST if request.method == "POST" else request.GET
    action = request.POST.get("action", "") if request.method == "POST" else ""
    visible = [key for key in batch.DATASET_KEYS if policy.screen(batch.DATASETS[key][1])]
    operable = {key for key in visible if policy.screen(batch.DATASETS[key][1], "operate")}

    if action == "commit":
        return _batch_commit(request, operable)

    dataset = source.get("dataset") if source.get("dataset") in visible else (visible[0] if visible else "")
    payload = _load_token(request.POST.get("token"), BATCH_SALT) if action == "back" else None
    if payload:
        dataset = payload["dataset"]
    filters = copy_service.read_filters(source)
    effective_from = (
        date.fromisoformat(payload["date"]) if payload and payload.get("date")
        else _parse_day(source.get("effective_from")) or copy_service.default_effective_from(today)
    )
    date_error = ""
    if dataset and not batch.is_immediate(dataset):
        try:
            copy_service.validate_effective_from(effective_from, today)
        except ValidationError as exc:
            date_error = exc.messages[0]
    models, truncated, _fixed = _listed_models(request, filters)
    rows = batch.build_rows(dataset, models, effective_from) if dataset else []
    errors = []
    notice = ""

    if payload:
        restored = {change["id"]: change["fields"] for change in payload["changes"]}
        for row in rows:
            row["selected"] = row["model"].pk in restored
            for cell in row["cells"]:
                new = restored.get(row["model"].pk, {}).get(cell["field"])
                cell["new"] = f"{int(new[1]):,}" if new else ""
    elif request.method == "POST":
        has_error = batch.read_inputs(dataset, rows, request.POST)
        if action == "apply":
            operation = request.POST.get("op")
            field = request.POST.get("op_field") or batch.dataset_fields(dataset)[0][0]
            try:
                amount = _signed_amount(request.POST.get("op_value"), operation)
                step = int(request.POST.get("op_round") or 1)
            except ValueError as exc:
                errors.append(f"調整數值：{exc}")
            else:
                if operation not in dict(batch.OPERATIONS) or step not in dict(batch.ROUNDING):
                    errors.append("請選擇調整方式。")
                elif not any(row.get("selected") for row in rows):
                    errors.append("請先勾選要套用的列。")
                else:
                    applied = batch.apply_operation(rows, field, operation, amount, step)
                    notice = f"已套用到 {applied} 列，確認無誤後按「預覽變更」。"
        elif action == "preview":
            if dataset not in operable:
                errors.append("你沒有這項資料的操作權限。")
            if date_error:
                errors.append(date_error)
            if has_error:
                errors.append("部分金額格式不正確，請修正標示的欄位。")
            if not errors:
                changes = batch.collect_changes(rows)
                if not changes:
                    errors.append("沒有任何變更：請勾選列並輸入與目前不同的新值。")
                else:
                    return _batch_preview(request, dataset, effective_from, changes, models, filters)

    result = request.session.pop("vehicle_model_batch_result", None) if request.GET.get("result") else None
    fields = batch.dataset_fields(dataset) if dataset else ()
    return render(request, "sales/vehicle_model_batch.html", {
        "stage": "result" if result else "edit",
        "result": result,
        "dataset": dataset,
        "dataset_label": batch.DATASETS[dataset][0] if dataset else "",
        "dataset_note": batch.DATASETS[dataset][4] if dataset else "",
        "immediate": bool(dataset and batch.is_immediate(dataset)),
        "can_operate": dataset in operable,
        "dataset_tabs": [
            {"key": key, "label": batch.DATASETS[key][0], "fields": "、".join(label for _name, label in batch.dataset_fields(key)),
             "query": urlencode({**_filter_query(filters), "dataset": key, "effective_from": effective_from.isoformat()})}
            for key in visible
        ],
        "fields": fields,
        "rows": rows,
        "truncated": truncated,
        "filters": filters,
        "filter_options": copy_service.filter_options(),
        "effective_from": effective_from,
        "date_error": date_error,
        "operations": batch.OPERATIONS,
        "rounding": batch.ROUNDING,
        "errors": errors,
        "notice": notice,
        "op": {
            "op": request.POST.get("op", "add"), "value": request.POST.get("op_value", ""),
            "field": request.POST.get("op_field", fields[0][0] if fields else ""),
            "round": request.POST.get("op_round", "1"),
        },
        "selected_count": sum(1 for row in rows if row.get("selected")),
        "today": today,
        "max_rows": batch.MAX_ROWS,
    })


def _signed_amount(raw, operation):
    """調整數值允許負數（加減金額、百分比）；統一設為只能是非負整數。"""
    from decimal import Decimal, InvalidOperation

    text = str(raw or "").strip().replace(",", "").replace("%", "").replace("$", "")
    if not text:
        raise ValueError("請輸入數值")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("請輸入數字") from exc
    if not value.is_finite():
        raise ValueError("請輸入數字")
    if operation == "set":
        return batch.parse_amount(text)
    if operation == "add" and value != value.to_integral_value():
        raise ValueError("加減金額只能是整數")
    if operation == "percent" and abs(value) > 1000:
        raise ValueError("百分比過大")
    return value


def _batch_preview(request, dataset, effective_from, changes, models, filters):
    immediate = batch.is_immediate(dataset)
    payload = {"dataset": dataset, "date": None if immediate else effective_from.isoformat(), "changes": changes}
    lines = batch.describe_changes(dataset, changes)
    return render(request, "sales/vehicle_model_batch.html", {
        "stage": "preview",
        "dataset": dataset,
        "dataset_label": batch.DATASETS[dataset][0],
        "dataset_note": batch.DATASETS[dataset][4],
        "immediate": immediate,
        "effective_from": effective_from,
        "fields": batch.dataset_fields(dataset),
        "lines": lines,
        "change_count": len(lines),
        "field_count": sum(len(line["fields"]) for line in lines),
        "token": signing.dumps(payload, salt=BATCH_SALT),
        "listed_ids": [model.pk for model in models],
        "filters": filters,
    })


def _batch_commit(request, operable):
    payload = _load_token(request.POST.get("token"), BATCH_SALT)
    back_url = reverse("vehicle_model_batch")
    if not payload:
        messages.error(request, "預覽已過期或內容不完整，資料尚未寫入；請重新預覽。")
        return redirect(back_url)
    dataset = payload["dataset"]
    if dataset not in operable:
        messages.error(request, "你沒有這項資料的操作權限，資料尚未寫入。")
        return redirect(back_url)
    day = date.fromisoformat(payload["date"]) if payload.get("date") else timezone.localdate()
    try:
        results = batch.commit_changes(dataset=dataset, changes=payload["changes"], effective_from=day,
                                       actor=request.user)
    except (ValidationError, IntegrityError) as exc:
        detail = "；".join(exc.messages) if isinstance(exc, ValidationError) else "資料剛被其他人變更"
        messages.error(request, f"批次調整未完成，未寫入任何資料：{detail}")
        return redirect(f"{back_url}?{urlencode({'dataset': dataset, 'effective_from': day.isoformat()})}")
    immediate = batch.is_immediate(dataset)
    route = {"price": "vehicle_model_price_versions", "commission": "vehicle_model_commission",
             "cost": "vehicle_model_settlement_costs", "incentive": "vehicle_model_incentives"}[dataset]
    lines = batch.describe_changes(dataset, [{"id": r["model_id"], "label": r["label"], "fields": r["fields"]}
                                             for r in results])
    request.session["vehicle_model_batch_result"] = {
        "dataset_label": batch.DATASETS[dataset][0],
        "immediate": immediate,
        "date": day.strftime("%Y/%m/%d"),
        "rows": [
            {"label": line["label"], "url": reverse(route, args=[line["id"]]),
             "fields": [{"label": field["label"], "old": None if field["old"] is None else f"{field['old']:,.0f}",
                         "new": f"{field['new']:,.0f}"} for field in line["fields"]]}
            for line in lines
        ],
    }
    when = "已立即生效" if immediate else f"將於 {day:%Y/%m/%d} 起生效"
    messages.success(request, f"已調整 {len(results)} 個年式的{batch.DATASETS[dataset][0]}，{when}。")
    return redirect(f"{back_url}?{urlencode({'dataset': dataset, 'result': 1})}")
