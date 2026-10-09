"""批次調整分期方案：像試算表一樣一次設定多個年式各期數的每期金額、分期公司、撥款比例與開辦費。

畫面帶入每個年式目前有效的方案；期數欄空白代表不提供該期數。每個期數各自有分期公司與撥款比例
（同一台車不同期數可能走不同分期公司）；開辦費以整台金額為準，個別期數可另填例外（例如只有遠信的期數收開辦費），
可用「期數條件」一次套用到多台。確認後依生效日建立新版本，
舊版本與已成立的訂單不受影響；同一天已有版本的年式不能批次調整，請到機種工作區處理。
"""
import json
import re
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from sales.models import InstallmentCompany, InstallmentPlanOption, InstallmentPlanVersion, VehicleModel
from sales.services.vehicle_model_batch import parse_amount
from sales.services.vehicle_model_copy import (
    _audit,
    current_version,
    current_versions_bulk,
    model_label,
    models_with_version_on,
    validate_effective_from,
    version_exists_on,
)

PERIODS = (12, 18, 24, 30, 36, 48, 60)  # 沒有 6 期；舊資料若有其他期數會原樣沿用
RATE = InstallmentPlanOption.ExpectedDisbursementMethod.RATE
FIXED = InstallmentPlanOption.ExpectedDisbursementMethod.FIXED
LOCKED_NOTE = "已有版本，請到機種工作區的「分期」分頁修改"


def _int(value):
    return None if value is None else int(Decimal(value))


def _rate_text(value):
    """撥款比例統一成去尾零的文字（92.50 → 92.5），用於比較與顯示。"""
    if value is None:
        return None
    text = format(Decimal(value).quantize(Decimal("0.01")), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def option_spec(option):
    return {
        "periods": option.periods,
        "company": option.company_id,
        "monthly": _int(option.monthly_amount),
        "fee": _int(option.opening_fee),
        "method": option.expected_disbursement_method,
        "rate": _rate_text(option.expected_disbursement_rate),
        "fixed": _int(option.expected_disbursement_fixed_amount),
        "bonus": _int(option.extra_disbursement_bonus) or 0,
    }


def fingerprint(specs):
    """版本內容的比較用文字：預覽後若有人改了方案，送出時就會不同。"""
    return "|".join(
        f"{s['periods']}:{s['company']}:{s['monthly']}:{s['fee']}:{s['method']}:{s['rate']}:{s['fixed']}:{s['bonus']}"
        for s in sorted(specs, key=lambda item: item["periods"])
    )


def extra_periods(specs):
    """表格欄位以外的期數（例如 42 期）：批次調整不顯示也不修改，原樣沿用。"""
    return sorted(spec["periods"] for spec in specs if spec["periods"] not in PERIODS)


def company_choices(rows=()):
    """啟用中的分期公司，加上目前方案仍在使用的停用公司（避免舊資料無法顯示）。"""
    used = {spec["company"] for row in rows for spec in row["specs"]}
    return list(InstallmentCompany.objects.filter(Q(active=True) | Q(pk__in=used)).order_by("name"))


def _specs_by_version(versions):
    options = InstallmentPlanOption.objects.filter(version__in=versions).order_by("periods")
    grouped = {}
    for option in options:
        grouped.setdefault(option.version_id, []).append(option_spec(option))
    return grouped


def _amount_text(value):
    return "" if value is None else f"{value:,}"


def _disbursement_note(spec):
    """非按比例試算的期數，撥款比例格留空並說明原本的撥款方式。"""
    if spec is None or spec["method"] == RATE:
        return ""
    if spec["method"] == FIXED:
        return f"固定撥款 ${spec['fixed']:,}"
    return "本單另填"


def row_fee(specs):
    """整台開辦費：取最多期數使用的金額（同數取較低者）；其餘期數視為例外。"""
    counts = {}
    for spec in specs:
        counts[spec["fee"]] = counts.get(spec["fee"], 0) + 1
    if not counts:
        return None
    return min(counts, key=lambda fee: (-counts[fee], fee))


def _fee_override(spec, base):
    return _amount_text(spec["fee"]) if spec and spec["fee"] != base else ""


def _cell(periods, spec, base):
    override = _fee_override(spec, base)
    return {
        "periods": periods,
        "current": spec["monthly"] if spec else None,
        "current_company": str(spec["company"]) if spec else "",
        "current_rate": (spec["rate"] or "") if spec else "",
        "note": _disbursement_note(spec),
        "value": _amount_text(spec["monthly"]) if spec else "",
        "company": str(spec["company"]) if spec else "",
        "rate": (spec["rate"] or "") if spec else "",
        "fee": override,
        "current_fee": override,
        "error": "",
    }


def build_rows(models, effective_from):
    ids = [model.pk for model in models]
    versions = current_versions_bulk("installment", ids, effective_from)
    taken = models_with_version_on("installment", ids, effective_from)
    grouped = _specs_by_version(list(versions.values()))
    rows = []
    for model in models:
        version = versions.get(model.pk)
        specs = grouped.get(version.pk, []) if version else []
        by_periods = {spec["periods"]: spec for spec in specs}
        base = row_fee(specs)
        locked = f"{effective_from:%Y/%m/%d} {LOCKED_NOTE}" if model.pk in taken else ""
        rows.append({
            "model": model,
            "label": model_label(model),
            "version": version,
            "specs": specs,
            "extra": extra_periods(specs),
            "locked": locked,
            "selected": False,
            "errors": [],
            "fee": _amount_text(base),
            "current_fee": _amount_text(base),
            "cells": [_cell(periods, by_periods.get(periods), base) for periods in PERIODS],
        })
    return rows


def restore_inputs(row, specs):
    """預覽頁「返回修改」：把預覽時的調整內容放回輸入框（原值欄位保持目前方案）。"""
    by_periods = {spec["periods"]: spec for spec in specs}
    row["selected"] = True
    base = row_fee(specs)
    row["fee"] = _amount_text(base)
    for cell in row["cells"]:
        spec = by_periods.get(cell["periods"])
        cell["value"] = _amount_text(spec["monthly"]) if spec else ""
        if spec:
            cell["company"] = str(spec["company"])
            cell["rate"] = spec["rate"] or ""
            cell["fee"] = _fee_override(spec, base)


def parse_rate(raw):
    text = str(raw or "").strip().replace("%", "").replace("％", "").strip()
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("撥款比例請輸入數字") from exc
    if not value.is_finite() or value < 0 or value > 100:
        raise ValueError("撥款比例需介於 0–100")
    if value != value.quantize(Decimal("0.01")):
        raise ValueError("撥款比例最多兩位小數")
    return _rate_text(value)


GRID_FIELD = re.compile(r"^(?:sel|fee|[pcrf]\d{1,2})_\d+$")


def grid_data(post):
    """畫面送出時把勾選列打包成一個 JSON 欄位（避免 32 列以上超過 Django 欄位數上限）；
    沒有打包欄位時（無 JavaScript）直接使用個別欄位。"""
    raw = post.get("grid")
    if not raw:
        return post
    try:
        values = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(values, dict):
        return {}
    return {key: str(value) for key, value in values.items() if isinstance(key, str) and GRID_FIELD.match(key)}


def read_inputs(rows, data, companies):
    """把畫面輸入套回列上，計算每個勾選列調整後的期數內容；回傳是否有錯誤。"""
    company_ids = {company.pk for company in companies}
    has_error = False
    for row in rows:
        pk = row["model"].pk
        row["selected"] = data.get(f"sel_{pk}") == "1" and not row["locked"]
        row["errors"] = []
        row["desired"] = None
        if not row["selected"]:
            continue  # 未勾選的列不送出內容，保留帶入的目前方案
        row["fee"] = (data.get(f"fee_{pk}") or "").strip()
        for cell in row["cells"]:
            periods = cell["periods"]
            cell["value"] = (data.get(f"p{periods}_{pk}") or "").strip()
            cell["company"] = (data.get(f"c{periods}_{pk}") or "").strip()
            cell["rate"] = (data.get(f"r{periods}_{pk}") or "").strip()
            cell["fee"] = (data.get(f"f{periods}_{pk}") or "").strip()
            cell["error"] = ""
        try:
            fee = parse_amount(row["fee"])
        except ValueError as exc:
            row["errors"].append(f"開辦費{exc}")
            fee = None
        row["desired"] = _desired_specs(row, fee, company_ids)
        row["errors"] += [f"{cell['periods']} 期：{cell['error']}" for cell in row["cells"] if cell["error"]]
        if row["errors"]:
            has_error = True
    return has_error


def _cell_spec(cell, old, fee, company_ids):
    """單一期數格的調整後內容；有錯誤時寫入 cell["error"] 並回傳 None。"""
    problems = []
    try:
        monthly = parse_amount(cell["value"])
    except ValueError as exc:
        cell["error"] = f"每期金額{exc}"
        return None
    if monthly <= 0:
        cell["error"] = "每期金額需大於 0"
        return None
    company = cell["company"]
    if not company:
        problems.append("請選擇分期公司")
    elif not company.isdigit() or int(company) not in company_ids:
        problems.append("請重新選擇分期公司")
    try:
        rate = parse_rate(cell["rate"])
    except ValueError as exc:
        problems.append(str(exc))
        rate = None
    else:
        if rate is None and old is None:
            problems.append("請填撥款比例")
    if problems:
        cell["error"] = "、".join(problems)
        return None
    spec = {"periods": cell["periods"], "company": int(company), "monthly": int(monthly), "fee": fee}
    if rate is None or (old and old["method"] == RATE and old["rate"] == rate):
        # 撥款比例留空（原本是固定金額或本單另填）或未改：沿用原撥款設定。
        spec.update({key: old[key] for key in ("method", "rate", "fixed", "bonus")})
    else:
        spec.update({"method": RATE, "rate": rate, "fixed": None, "bonus": old["bonus"] if old else 0})
    return spec


def _desired_specs(row, fee, company_ids):
    """fee 為整台開辦費（空白視為 0）；期數格另填的開辦費是例外，優先採用。"""
    existing = {spec["periods"]: spec for spec in row["specs"]}
    specs = []
    for cell in row["cells"]:
        if not cell["value"]:
            continue
        old = existing.get(cell["periods"])
        try:
            override = parse_amount(cell["fee"])
        except ValueError as exc:
            cell["error"] = f"開辦費{exc}"
            continue
        period_fee = int(override) if override is not None else int(fee or 0)
        spec = _cell_spec(cell, old, period_fee, company_ids)
        if spec:
            specs.append(spec)
    specs.extend(existing[periods] for periods in row["extra"])  # 表格以外的期數沿用原值
    return sorted(specs, key=lambda spec: spec["periods"])


def collect_changes(rows):
    changes = []
    for row in rows:
        if not row["selected"] or row["locked"] or row.get("desired") is None:
            continue
        if fingerprint(row["desired"]) == fingerprint(row["specs"]):
            continue
        changes.append({
            "id": row["model"].pk,
            "label": row["label"],
            "source": fingerprint(row["specs"]),
            "old": row["specs"],
            "new": row["desired"],
        })
    return changes


def _disbursement_text(spec):
    if spec["method"] == RATE:
        text = f"撥款 {spec['rate']}%"
    elif spec["method"] == FIXED:
        text = f"撥款 ${spec['fixed']:,}"
    else:
        text = "撥款本單另填"
    return text + (f"＋獎金 ${spec['bonus']:,}" if spec["bonus"] else "")


def describe_changes(changes):
    """預覽與結果用：每個年式列出新增、移除與調整的期數。"""
    names = dict(InstallmentCompany.objects.values_list("pk", "name"))
    lines = []
    for change in changes:
        old = {spec["periods"]: spec for spec in change["old"]}
        new = {spec["periods"]: spec for spec in change["new"]}
        periods_rows = []
        for periods in sorted(set(old) | set(new)):
            before, after = old.get(periods), new.get(periods)
            if before == after:
                continue
            details = []
            if before and after:
                if before["company"] != after["company"]:
                    details.append(f"分期公司 {names.get(before['company'], '—')} → {names.get(after['company'], '—')}")
                if before["fee"] != after["fee"]:
                    details.append(f"開辦費 ${before['fee']:,} → ${after['fee']:,}")
                if _disbursement_text(before) != _disbursement_text(after):
                    details.append(f"{_disbursement_text(before)} → {_disbursement_text(after)}")
            periods_rows.append({
                "periods": periods,
                "status": "add" if before is None else ("remove" if after is None else "change"),
                "old_monthly": before["monthly"] if before else None,
                "new_monthly": after["monthly"] if after else None,
                "diff": after["monthly"] - before["monthly"] if before and after else None,
                "summary": (
                    f"{names.get(after['company'], '—')}・開辦費 ${after['fee']:,}・{_disbursement_text(after)}"
                    if after else ""
                ),
                "details": details,
            })
        lines.append({
            "id": change["id"],
            "label": change["label"],
            "periods": periods_rows,
            "stops": bool(change["old"]) and not change["new"],
        })
    return lines


@transaction.atomic
def commit_changes(*, changes, effective_from, actor):
    """重新讀取目前方案，與預覽時不同就整批不寫入，避免覆蓋他人剛做的調整。"""
    validate_effective_from(effective_from)
    models = VehicleModel.objects.select_for_update().in_bulk([change["id"] for change in changes])
    if len(models) != len(changes):
        raise ValidationError("部分年式已不存在，請重新預覽。")
    stale = []
    for change in changes:
        if version_exists_on("installment", change["id"], effective_from):
            stale.append(f"{change['label']}：{effective_from:%Y/%m/%d} {LOCKED_NOTE}")
            continue
        version = current_version("installment", change["id"], effective_from)
        specs = [option_spec(option) for option in version.options.all()] if version else []
        if fingerprint(specs) != change["source"]:
            stale.append(f"{change['label']}：目前方案已變更")
    company_ids = {spec["company"] for change in changes for spec in change["new"]}
    if InstallmentCompany.objects.filter(pk__in=company_ids).count() != len(company_ids):
        stale.append("部分分期公司已不存在")
    if stale:
        raise ValidationError(["預覽後資料已被變更，未寫入任何資料；請重新預覽。", *stale])

    today = timezone.localdate()
    results = []
    for change in changes:
        version = InstallmentPlanVersion.objects.create(
            vehicle_model=models[change["id"]], announced_on=today, effective_from=effective_from,
            note=f"批次調整（{today:%Y/%m/%d}）", active=True,
        )
        for spec in change["new"]:
            option = InstallmentPlanOption(
                version=version, periods=spec["periods"], company_id=spec["company"],
                monthly_amount=spec["monthly"], opening_fee=spec["fee"],
                expected_disbursement_method=spec["method"],
                expected_disbursement_rate=None if spec["rate"] is None else Decimal(spec["rate"]),
                expected_disbursement_fixed_amount=spec["fixed"],
                extra_disbursement_bonus=spec["bonus"],
            )
            option.full_clean()
            option.save()
        results.append({"model_id": change["id"], "label": change["label"], "version_id": version.pk,
                        "periods": [spec["periods"] for spec in change["new"]]})
    _audit(
        actor, "update",
        f"批次調整分期方案：{len(results)} 個年式，{effective_from:%Y/%m/%d} 起生效",
        {"tool": "installment_batch", "effective_from": effective_from.isoformat(), "results": results},
    )
    return results
