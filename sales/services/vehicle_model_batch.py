"""批次調整：一次為多個年式建立新的售價／成本／原廠獎勵版本，或更新車行基礎傭金。

有生效日的資料只新增版本、不改舊版本；車行基礎傭金沒有版本，儲存即生效並記錄原值與新值。
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from sales.models import (
    VehicleIncentiveRule,
    VehicleModel,
    VehiclePriceVersion,
    VehicleSettlementCostRule,
)
from sales.services.vehicle_model_copy import (
    _audit,
    current_version,
    current_versions_bulk,
    model_label,
    models_with_version_on,
    validate_effective_from,
    version_exists_on,
)

# 代號: (名稱, 畫面權限, 欄位[(欄位, 名稱)], 是否立即生效, 說明)
DATASETS = {
    "price": ("售價", "models", (("cash_price", "現金價"), ("suggested_price", "建議售價")), False,
              "建立新的售價版本；是否含牌險沿用目前版本。"),
    "commission": ("車行基礎傭金", "commissions", (("base_dealer_commission", "基礎傭金"),), True,
                   "基礎傭金沒有版本，確認後立即生效，原值與新值記入異動紀錄。"),
    "cost": ("結算成本", "costs", (("amount", "代銷結算成本"),), False,
             "建立新的結算成本版本，依領牌日套用。"),
    "incentive": ("原廠獎勵與補助", "incentives", (
        ("sales_bonus", "實銷獎勵金"), ("promotion_subsidy", "促銷補助金"),
        ("installment_interest_subsidy", "分期補貼息"),
    ), False, "建立新的獎勵補助版本，依領牌日套用。"),
}
DATASET_KEYS = tuple(DATASETS)
OPERATIONS = (("add", "加減金額"), ("percent", "百分比"), ("set", "統一設為"))
ROUNDING = ((1, "不進位"), (10, "十元"), (100, "百元"), (1000, "千元"))
MAX_ROWS = 300
MAX_AMOUNT = Decimal("9999999999")


def dataset_fields(dataset):
    return DATASETS[dataset][2]


def is_immediate(dataset):
    return DATASETS[dataset][3]


def parse_amount(raw):
    """接受千分位、$、元與空白；回傳非負整數 Decimal，空白回傳 None。"""
    text = str(raw or "").strip().replace(",", "").replace("，", "").replace("$", "").replace("元", "").strip()
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("請輸入數字") from exc
    if not value.is_finite():
        raise ValueError("請輸入數字")
    if value < 0:
        raise ValueError("金額不可小於 0")
    if value != value.to_integral_value():
        raise ValueError("金額只能是整數")
    if value > MAX_AMOUNT:
        raise ValueError("金額過大")
    return value.quantize(Decimal("1"))


def apply_adjustment(current, operation, amount, step=1):
    """加減金額、百分比或統一設為；結果依進位單位四捨五入，不可小於 0。目前沒有值時只有「統一設為」可用。"""
    amount = Decimal(str(amount))
    step = Decimal(str(step or 1))
    if operation == "set":
        result = amount
    elif current is None:
        return None
    elif operation == "add":
        result = Decimal(current) + amount
    elif operation == "percent":
        result = Decimal(current) * (Decimal("100") + amount) / Decimal("100")
    else:
        raise ValueError(operation)
    result = (result / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step
    if result < 0:
        raise ValueError("調整後金額小於 0")
    return result


def _values_from(dataset, model, effective_from, version, exists_on_day):
    fields = [name for name, _label in dataset_fields(dataset)]
    if dataset == "commission":
        return {"base_dealer_commission": model.base_dealer_commission}, None, ""
    values = {name: (getattr(version, name) if version else None) for name in fields}
    if version is not None and version.effective_from == effective_from:
        return values, version, f"{effective_from:%Y/%m/%d} 已有版本，請到機種工作區修改"
    if exists_on_day:
        return values, version, f"{effective_from:%Y/%m/%d} 已有停用版本，請到機種工作區處理"
    return values, version, ""


def current_values(dataset, model, effective_from):
    """回傳 (目前值 {欄位: 值}, 來源版本, 不可調整原因)。"""
    if dataset == "commission":
        return _values_from(dataset, model, effective_from, None, False)
    version = current_version(dataset, model.pk, effective_from)
    return _values_from(dataset, model, effective_from, version,
                        version_exists_on(dataset, model.pk, effective_from))


def build_rows(dataset, models, effective_from):
    ids = [model.pk for model in models]
    if dataset == "commission":
        versions, taken = {}, set()
    else:
        versions = current_versions_bulk(dataset, ids, effective_from)
        taken = models_with_version_on(dataset, ids, effective_from)
    rows = []
    for model in models:
        values, version, locked = _values_from(dataset, model, effective_from, versions.get(model.pk),
                                               model.pk in taken)
        rows.append({
            "model": model,
            "label": model_label(model),
            "version": version,
            "locked": locked,
            "cells": [
                {"field": name, "label": label, "current": values[name], "new": "", "error": ""}
                for name, label in dataset_fields(dataset)
            ],
        })
    return rows


def read_inputs(dataset, rows, data):
    """把畫面輸入套回列上；回傳 (是否有錯誤)。"""
    has_error = False
    for row in rows:
        pk = row["model"].pk
        row["selected"] = data.get(f"sel_{pk}") == "1" and not row["locked"]
        for cell in row["cells"]:
            raw = (data.get(f"new_{cell['field']}_{pk}") or "").strip()
            cell["new"] = raw
            cell["error"] = ""
            if not raw or not row["selected"]:
                continue
            try:
                cell["parsed"] = parse_amount(raw)
            except ValueError as exc:
                cell["error"] = str(exc)
                has_error = True
    return has_error


def apply_operation(rows, field, operation, amount, step):
    """伺服器端套用（無 JavaScript 時的同一算法）：只處理已勾選的列。"""
    applied = 0
    for row in rows:
        if not row.get("selected"):
            continue
        for cell in row["cells"]:
            if cell["field"] != field:
                continue
            try:
                result = apply_adjustment(cell["current"], operation, amount, step)
            except ValueError as exc:
                cell["error"] = str(exc)
                continue
            if result is None:
                cell["error"] = "目前沒有金額，只能用「統一設為」"
                continue
            cell["new"] = f"{result:,.0f}"
            cell["error"] = ""
            applied += 1
    return applied


def collect_changes(rows):
    """只收已勾選、且新值與目前值不同的列；未輸入的欄位視為不變。"""
    changes = []
    for row in rows:
        if not row.get("selected") or row["locked"]:
            continue
        fields = {}
        for cell in row["cells"]:
            if cell.get("error") or not cell["new"]:
                continue
            new = cell.get("parsed")
            if new is None:
                new = parse_amount(cell["new"])
            old = cell["current"]
            if old is None or Decimal(old) != new:
                fields[cell["field"]] = [None if old is None else str(Decimal(old).quantize(Decimal("1"))), str(new)]
        if fields:
            changes.append({"id": row["model"].pk, "label": row["label"], "fields": fields})
    return changes


def describe_changes(dataset, changes):
    labels = dict(dataset_fields(dataset))
    lines = []
    for change in changes:
        fields = []
        for name, (old, new) in change["fields"].items():
            old_value = None if old is None else Decimal(old)
            new_value = Decimal(new)
            diff = None if old_value is None else new_value - old_value
            percent = None
            if old_value not in (None, Decimal("0")):
                percent = (diff / old_value * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            fields.append({"name": name, "label": labels[name], "old": old_value, "new": new_value,
                           "diff": diff, "percent": percent})
        lines.append({"id": change["id"], "label": change["label"], "fields": fields})
    return lines


@transaction.atomic
def commit_changes(*, dataset, changes, effective_from, actor):
    """重新讀取目前值，與預覽時的原值不同就整批不寫入，避免覆蓋他人剛做的調整。"""
    immediate = is_immediate(dataset)
    if not immediate:
        validate_effective_from(effective_from)
    models = VehicleModel.objects.select_for_update().in_bulk([change["id"] for change in changes])
    if len(models) != len(changes):
        raise ValidationError("部分年式已不存在，請重新預覽。")
    stale = []
    for change in changes:
        model = models[change["id"]]
        values, _version, locked = current_values(dataset, model, effective_from)
        if locked:
            stale.append(f"{change['label']}：{locked}")
            continue
        for name, (old, _new) in change["fields"].items():
            current = values[name]
            current_text = None if current is None else str(Decimal(current).quantize(Decimal("1")))
            if current_text != old:
                stale.append(f"{change['label']}：目前值已變更")
                break
    if stale:
        raise ValidationError(["預覽後資料已被變更，未寫入任何資料；請重新預覽。", *stale])

    today = timezone.localdate()
    results = []
    for change in changes:
        model = models[change["id"]]
        new_values = {name: Decimal(new) for name, (_old, new) in change["fields"].items()}
        values, version, _locked = current_values(dataset, model, effective_from)
        note = f"批次調整（{today:%Y/%m/%d}）"
        if dataset == "commission":
            model.base_dealer_commission = new_values["base_dealer_commission"]
            model.save(update_fields=["base_dealer_commission", "updated_at"])
            created_id = None
        elif dataset == "price":
            created = VehiclePriceVersion.objects.create(
                vehicle_model=model,
                cash_price=new_values.get("cash_price", values["cash_price"]),
                suggested_price=new_values.get("suggested_price", values["suggested_price"]),
                suggested_price_includes_registration=(
                    version.suggested_price_includes_registration if version else True
                ),
                announced_on=today,
                effective_from=effective_from,
                source_note=note,
                active=True,
            )
            created_id = created.pk
        elif dataset == "cost":
            created = VehicleSettlementCostRule.objects.create(
                vehicle_model=model, amount=new_values["amount"], announced_on=today,
                effective_from=effective_from, note=note, active=True,
            )
            created_id = created.pk
        elif dataset == "incentive":
            merged = {name: new_values.get(name, values[name] if values[name] is not None else Decimal("0"))
                      for name, _label in dataset_fields(dataset)}
            created = VehicleIncentiveRule.objects.create(
                vehicle_model=model, announced_on=today, effective_from=effective_from, note=note, active=True,
                **merged,
            )
            created_id = created.pk
        else:
            raise ValueError(dataset)
        results.append({"model_id": model.pk, "label": change["label"], "fields": change["fields"],
                        "version_id": created_id})
    label = DATASETS[dataset][0]
    when = "立即生效" if immediate else f"{effective_from:%Y/%m/%d} 起生效"
    _audit(
        actor, "update",
        f"批次調整{label}：{len(results)} 個年式，{when}",
        {"tool": "vehicle_model_batch", "dataset": dataset,
         "effective_from": None if immediate else effective_from.isoformat(), "results": results},
    )
    return results
