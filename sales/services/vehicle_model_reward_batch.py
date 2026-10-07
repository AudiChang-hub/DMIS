"""批次套用附加獎勵：為多個年式一次建立同一組車行附加獎勵方案。

只新增方案；唯一會改動的既有資料是「沒有結束日、且在新方案生效前已開始」的原方案——
勾選自動結束時把它設為新方案前一天結束。已設定結束日的方案、之後才開始的排定方案、
同一天開始的方案一律不動，該年式略過並說明原因。
訂單建立時已存附加獎勵快照（SalesOrder.dealer_reward_snapshot），結束原方案不影響既有訂單。
"""
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch, Q
from django.utils import timezone

from sales.models import (
    DealerRewardCatalogItem,
    DealerRewardCostVersion,
    DealerVehicleRewardItem,
    DealerVehicleRewardPlan,
    VehicleModel,
)
from sales.services.vehicle_model_copy import _audit, model_label, validate_effective_from

MAX_ITEMS = 20
MAX_QUANTITY = 999_999_999
ITEM_NOTE_MAX = 250
PLAN_NOTE_MAX = 500

CREATE, CLOSE, SKIP = "create", "close", "skip"


def fmt_day(day):
    return f"{day:%Y/%m/%d}"


# ---------------------------------------------------------------------------
# 品項
# ---------------------------------------------------------------------------

def catalog_items(ids=None):
    """啟用中的獎勵品項，並預先載入啟用的成本版本（cost_version_on 會用到）。"""
    queryset = DealerRewardCatalogItem.objects.filter(active=True)
    if ids is not None:
        queryset = queryset.filter(pk__in=ids)
    return list(
        queryset.prefetch_related(Prefetch(
            "cost_versions",
            queryset=DealerRewardCostVersion.objects.filter(active=True).order_by("-effective_from", "-id"),
            to_attr="prefetched_cost_versions",
        )).order_by("reward_type", "name", "unit")
    )


def catalog_groups(items):
    """依類型分組（順序同類型選項），供下拉選單 optgroup 使用。"""
    groups = []
    for value, label in DealerVehicleRewardItem.RewardType.choices:
        members = [item for item in items if item.reward_type == value]
        if members:
            groups.append({"label": label, "items": members})
    return groups


def catalog_metadata(items):
    return {
        str(item.pk): {
            "name": item.name,
            "type": item.get_reward_type_display(),
            "unit": item.unit,
            "costs": [
                {"from": version.effective_from.isoformat(),
                 "to": version.effective_to.isoformat() if version.effective_to else "",
                 "amount": int(version.unit_cost)}
                for version in item.prefetched_cost_versions
            ],
        }
        for item in items
    }


def parse_quantity(raw):
    """數量只收正整數（可含千分位）；空白回傳 None。"""
    text = str(raw or "").strip().replace(",", "").replace("，", "")
    if not text:
        return None
    if not text.isdigit():
        raise ValueError("數量只能是正整數")
    value = int(text)
    if value < 1:
        raise ValueError("數量至少為 1")
    if value > MAX_QUANTITY:
        raise ValueError("數量過大")
    return value


def read_items(source, catalog_by_id):
    """讀取重複的品項列（item_catalog／item_quantity／item_note 平行陣列）。

    回傳 (rows, errors)。整列空白會略過；rows 保留原輸入供畫面回填。
    """
    catalogs = source.getlist("item_catalog")
    quantities = source.getlist("item_quantity")
    notes = source.getlist("item_note")
    count = max(len(catalogs), len(quantities), len(notes))
    rows, errors, seen = [], [], set()
    for index in range(count):
        raw_catalog = (catalogs[index] if index < len(catalogs) else "").strip()
        raw_quantity = (quantities[index] if index < len(quantities) else "").strip()
        note = (notes[index] if index < len(notes) else "").strip()
        if not raw_catalog and not raw_quantity and not note:
            continue
        row = {"catalog_id": raw_catalog, "quantity_raw": raw_quantity, "note": note,
               "catalog": None, "quantity": None, "error": ""}
        rows.append(row)
        catalog = catalog_by_id.get(int(raw_catalog)) if raw_catalog.isdigit() else None
        problems = []
        if catalog is None:
            problems.append("請選擇啟用中的獎勵品項" if not raw_catalog else "此品項已停用或不存在，請重新選擇")
        elif catalog.pk in seen:
            problems.append("同一方案不可重複填寫相同獎勵")
        else:
            seen.add(catalog.pk)
            row["catalog"] = catalog
        try:
            row["quantity"] = parse_quantity(raw_quantity)
            if row["quantity"] is None:
                problems.append("請填寫數量")
        except ValueError as exc:
            problems.append(str(exc))
        if len(note) > ITEM_NOTE_MAX:
            problems.append(f"說明最多 {ITEM_NOTE_MAX} 字")
        row["error"] = "；".join(problems)
    if any(row["error"] for row in rows):
        errors.append("部分獎勵項目需要修正，請查看標示的列。")
    if not rows:
        errors.append("請至少填寫一項獎勵。")
    if len(rows) > MAX_ITEMS:
        errors.append(f"一個方案最多 {MAX_ITEMS} 項獎勵。")
    return rows, errors


def cost_lines(items, day):
    """每項依生效日的成本版本估算；回傳 (lines, 每台預估成本, 是否有未維護成本)。"""
    lines, total, missing = [], 0, False
    for catalog, quantity, note in items:
        version = catalog.cost_version_on(day)
        unit_cost = int(version.unit_cost) if version else None
        line_total = unit_cost * quantity if unit_cost is not None else None
        if line_total is None:
            missing = True
        else:
            total += line_total
        lines.append({"catalog": catalog, "quantity": quantity, "note": note, "unit_cost": unit_cost,
                      "total": line_total, "label": f"{catalog.name} {quantity:,} {catalog.unit}"})
    return lines, total, missing


def items_text(lines):
    return "、".join(line["label"] for line in lines)


# ---------------------------------------------------------------------------
# 原方案判斷
# ---------------------------------------------------------------------------

def plan_items_text(plan):
    return "、".join(f"{item.name} {int(item.quantity):,} {item.unit}" for item in plan.items.all())


def plan_summary(plan):
    """「郵政禮券 10,000 元、機油 2 瓶（至 2026/12/31）」；沒有方案回傳「無」。"""
    if plan is None:
        return "無"
    text = plan_items_text(plan) or "尚未填寫項目"
    return f"{text}（至 {fmt_day(plan.effective_to)}）" if plan.effective_to else text


def plan_period(plan):
    if plan.effective_to:
        return f"{fmt_day(plan.effective_from)}–{fmt_day(plan.effective_to)}"
    return f"{fmt_day(plan.effective_from)} 起・未設結束日"


def related_plans(model_ids, start):
    """會影響判斷的方案：啟用且結束日不早於新方案生效日，或同一天開始（含停用，受唯一鍵限制）。"""
    queryset = (
        DealerVehicleRewardPlan.objects.filter(vehicle_model_id__in=model_ids)
        .filter(Q(effective_from=start) | (Q(active=True) & (Q(effective_to__isnull=True) | Q(effective_to__gte=start))))
        .prefetch_related("items")
        .order_by("vehicle_model_id", "effective_from", "id")
    )
    by_model = {}
    for plan in queryset:
        by_model.setdefault(plan.vehicle_model_id, []).append(plan)
    return by_model


def decide(plans, start, end, close_open):
    """單一年式的處理方式：create／close（結束原方案後新增）／skip（附原因）。"""
    current = next((plan for plan in plans if plan.active and plan.effective_from <= start
                    and (plan.effective_to is None or plan.effective_to >= start)), None)
    result = {"status": CREATE, "reason": "", "current": current, "close_plan": None, "close_to": None}
    same_day = next((plan for plan in plans if plan.effective_from == start), None)
    if same_day is not None:
        state = "" if same_day.active else "（已停用）"
        result.update(status=SKIP, reason=f"{fmt_day(start)} 已有開始的方案{state}，請到「傭金與獎勵」分頁修改該方案")
        return result
    overlapping = [
        plan for plan in plans
        if plan.active and (plan.effective_to is None or plan.effective_to >= start)
        and (end is None or plan.effective_from <= end)
    ]
    closable = None
    for plan in overlapping:
        if plan.effective_to is not None:
            result.update(status=SKIP, reason=(
                f"原方案（{plan_period(plan)}）已設定結束日，與新方案期間重疊；"
                "已排定的期間不自動修改，請到「傭金與獎勵」分頁調整"))
            return result
        if plan.effective_from > start:
            result.update(status=SKIP, reason=(
                f"已排定 {fmt_day(plan.effective_from)} 起的方案，與新方案期間重疊；請縮短新方案結束日或調整排定方案"))
            return result
        closable = plan
    if closable is not None:
        if not close_open:
            result.update(status=SKIP, reason=(
                f"原方案（{fmt_day(closable.effective_from)} 起）沒有結束日，與新方案重疊；"
                "勾選「自動設為新方案前一天結束」或先到「傭金與獎勵」分頁設定結束日"))
            return result
        result.update(status=CLOSE, close_plan=closable, close_to=start - timedelta(days=1))
    return result


def build_rows(models, start, end, close_open, selected=()):
    ids = [model.pk for model in models]
    plans = related_plans(ids, start) if start else {}
    rows = []
    for model in models:
        decision = decide(plans.get(model.pk, []), start, end, close_open) if start else {
            "status": CREATE, "reason": "", "current": None, "close_plan": None, "close_to": None}
        rows.append({
            "model": model,
            "label": model_label(model),
            "selected": model.pk in selected,
            "current_summary": plan_summary(decision["current"]),
            "current_period": plan_period(decision["current"]) if decision["current"] else "",
            **decision,
        })
    return rows


def plans_metadata(models, today):
    """畫面即時判斷用：今天之後仍可能影響新方案的方案（JS 與 decide() 同一規則，送出時以伺服器為準）。"""
    ids = [model.pk for model in models]
    queryset = (
        DealerVehicleRewardPlan.objects.filter(vehicle_model_id__in=ids)
        .filter(Q(effective_from__gte=today) | (Q(active=True) & (Q(effective_to__isnull=True) | Q(effective_to__gte=today))))
        .prefetch_related("items").order_by("vehicle_model_id", "effective_from", "id")
    )
    data = {str(pk): [] for pk in ids}
    for plan in queryset:
        data[str(plan.vehicle_model_id)].append({
            "id": plan.pk, "from": plan.effective_from.isoformat(),
            "to": plan.effective_to.isoformat() if plan.effective_to else "",
            "active": plan.active, "items": plan_items_text(plan) or "尚未填寫項目",
        })
    return data


def validate_period(start, end, today=None):
    errors = []
    try:
        validate_effective_from(start, today)
    except ValidationError as exc:
        errors.extend(exc.messages)
    if start and end and end < start:
        errors.append("結束日不可早於生效日。")
    return errors


# ---------------------------------------------------------------------------
# 寫入
# ---------------------------------------------------------------------------

@transaction.atomic
def commit(*, payload, actor):
    """依簽章後的預覽內容寫入；重新判斷每個年式與品項成本，與預覽不同就整批不寫入。"""
    start = date.fromisoformat(payload["start"])
    end = date.fromisoformat(payload["end"]) if payload.get("end") else None
    close_open = bool(payload.get("close_open"))
    errors = validate_period(start, end)
    if errors:
        raise ValidationError(errors)
    expected = {int(pk): entry for pk, entry in payload["models"].items()}
    models = VehicleModel.objects.select_for_update().in_bulk(list(expected))
    if len(models) != len(expected):
        raise ValidationError("部分年式已不存在，請重新預覽。")
    list(DealerVehicleRewardPlan.objects.select_for_update().filter(vehicle_model_id__in=list(expected)))

    catalog_by_id = {item.pk: item for item in catalog_items([row[0] for row in payload["items"]])}
    stale = []
    items = []
    for catalog_id, quantity, note in payload["items"]:
        catalog = catalog_by_id.get(catalog_id)
        if catalog is None:
            stale.append("部分獎勵品項已停用或刪除")
            continue
        items.append((catalog, quantity, note))
    lines, per_unit, _missing = cost_lines(items, start) if not stale else ([], 0, False)
    if not stale and [line["unit_cost"] for line in lines] != payload["unit_costs"]:
        stale.append("獎勵品項的成本版本已變更")

    plans = related_plans(list(expected), start)
    decisions = {}
    for pk, entry in expected.items():
        decision = decide(plans.get(pk, []), start, end, close_open)
        decisions[pk] = decision
        close_id = decision["close_plan"].pk if decision["close_plan"] else None
        if decision["status"] != entry["status"] or close_id != entry.get("close_id"):
            label = model_label(models[pk])
            stale.append(f"{label}：{decision['reason'] or '原方案已變更'}")
    if stale:
        raise ValidationError(["預覽後資料已被變更，未寫入任何資料；請重新預覽。", *stale])

    today = timezone.localdate()
    note = payload.get("note") or f"批次套用附加獎勵（{fmt_day(today)}）"
    order = sorted(expected, key=lambda pk: (models[pk].brand.casefold(), models[pk].name.casefold(),
                                            -(models[pk].model_year or 0), pk))
    results = []
    for pk in order:
        model, decision = models[pk], decisions[pk]
        closed = None
        if decision["status"] == CLOSE:
            closed = decision["close_plan"]
            closed.effective_to = decision["close_to"]
            closed.save(update_fields=["effective_to", "updated_at"])
        plan = DealerVehicleRewardPlan(vehicle_model=model, effective_from=start, effective_to=end, active=True,
                                       note=note)
        plan.save()
        for line in lines:
            catalog = line["catalog"]
            DealerVehicleRewardItem(
                plan=plan, catalog_item=catalog, reward_type=catalog.reward_type, name=catalog.name,
                quantity=line["quantity"], unit=catalog.unit, unit_cost_snapshot=line["unit_cost"],
                cost_effective_on_snapshot=start, note=line["note"],
            ).save()
        results.append({
            "model_id": pk, "label": model_label(model), "plan_id": plan.pk,
            "previous_id": decision["current"].pk if decision["current"] else None,
            "closed_id": closed.pk if closed else None,
            "closed_to": closed.effective_to.isoformat() if closed else None,
        })
    closed_count = sum(1 for row in results if row["closed_id"])
    period = f"{fmt_day(start)} 起" + (f"至 {fmt_day(end)}" if end else "")
    _audit(
        actor, "update",
        f"批次套用附加獎勵：{len(results)} 個年式，{period}（{items_text(lines)}）"
        + (f"，結束原方案 {closed_count} 個" if closed_count else ""),
        {
            "tool": "vehicle_model_reward_batch",
            "effective_from": start.isoformat(),
            "effective_to": end.isoformat() if end else None,
            "close_open": close_open,
            "note": note,
            "items": [
                {"catalog_item_id": line["catalog"].pk, "name": line["catalog"].name, "quantity": line["quantity"],
                 "unit": line["catalog"].unit, "unit_cost": line["unit_cost"], "note": line["note"]}
                for line in lines
            ],
            "per_unit_cost": per_unit,
            "results": results,
            "skipped": payload.get("skipped", []),
        },
    )
    return results, lines
