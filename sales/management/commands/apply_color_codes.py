"""依原廠「色碼＋廣告色」對應表更正訂單車色（T-223，使用者 2026-11-17 選方案 A）。

對應表（xlsx 或 csv，第一列為標題）要有四欄：車型（品牌＋車型名稱）、引擎號碼（電動車為車身號碼）、
顏色代碼、廣告色；欄名含「車型」「號碼」「代碼／色碼」「廣告色」即可，其他欄忽略。

- 預設 dry-run：不寫入，只輸出預覽 CSV（訂單、車型、原車色→新車色＋色碼、建立或沿用哪個車色、略過原因）與統計。
- --apply：在同一個交易內寫入。
  - 每個車型下找同名（不分大小寫、去頭尾空白）的車色：有就補上色碼、啟用狀態不動；沒有就新建，一律停用。
  - 訂單車色改指到該車色，每張單留一筆 OrderChange；已配庫存車在同一交易改成同一個車色，每台留一筆庫存異動紀錄
    （使用者 2026-11-17 選 A）。預覽 CSV 的「已配庫存車車色」欄顯示「原→新」。
  - 舊的通用色（白、黑、灰…）不刪除、啟用狀態不動。
- 只處理台鈴品牌（SUZUKI、eReady）；同一車型同一廣告色出現多個色碼、同名車色已有不同色碼、車型與對應表不符等情況略過並寫明原因。
- 冪等：訂單與已配庫存車都已指到目標車色時列為「不變」，再跑一次不會重複寫入。
"""
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from sales.models import (
    OrderChange, SalesOrder, VehicleColor, VehicleInventory, VehicleInventoryHistory, normalize_vehicle_identifier,
)

ACTOR = "PM（使用者指示）"
REASON = "T-223 依原廠色碼表更正車色為廣告色＋色碼"
SUZUKI_BRANDS = {"suzuki", "eready"}
PREVIEW_HEADERS = [
    "訂單編號", "訂單ID", "訂單狀態", "品牌", "車型", "型號", "年式", "引擎／車身號碼",
    "原車色", "新車色", "色碼", "車色處理", "結果", "略過原因", "已配庫存車車色",
]


@dataclass
class ColorPlan:
    vehicle_model_id: int
    name: str
    code: str
    existing: VehicleColor | None = None
    action: str = ""
    skip: str = ""
    orders: list = field(default_factory=list)


def _key(text):
    return " ".join(str(text or "").split()).casefold()


def _header_index(headers):
    wanted = {"model": ("車型",), "ident": ("號碼",), "code": ("代碼", "色碼"), "name": ("廣告色",)}
    index = {}
    for position, header in enumerate(headers):
        text = str(header or "").strip()
        for key, words in wanted.items():
            if key in index:
                continue
            if key == "name" and text != "廣告色":
                continue
            if any(word in text for word in words) and not (key == "model" and "號碼" in text):
                index[key] = position
                break
    missing = [key for key in wanted if key not in index]
    if missing:
        raise CommandError(f"對應表缺少欄位：{'、'.join(missing)}（需要 車型、引擎號碼、顏色代碼、廣告色）")
    return index


def read_mapping(path):
    path = Path(path)
    if not path.exists():
        raise CommandError(f"找不到對應表：{path}")
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        from openpyxl import load_workbook
        workbook = load_workbook(path, read_only=True, data_only=True)
        rows = list(workbook.worksheets[0].iter_rows(values_only=True))
        workbook.close()
    else:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
    if not rows:
        raise CommandError("對應表是空的。")
    index = _header_index(rows[0])
    mapping = defaultdict(set)
    for row in rows[1:]:
        cells = list(row) + [None] * 8
        ident = normalize_vehicle_identifier(str(cells[index["ident"]] or ""))
        if not ident:
            continue
        code = "".join(str(cells[index["code"]] or "").split()).upper()
        name = str(cells[index["name"]] or "").strip()
        mapping[ident].add((_key(cells[index["model"]]), code, name))
    return mapping


def order_identifiers(order):
    values = set()
    vehicle = order.allocated_vehicle
    if vehicle:
        values |= {vehicle.normalized_engine_number, vehicle.normalized_frame_number}
    snapshot = getattr(order, "legacy_snapshot", None)
    if snapshot:
        values.add(normalize_vehicle_identifier(snapshot.vehicle_identifier))
        data = snapshot.import_row.mapped_data or {}
        values.add(normalize_vehicle_identifier(str(data.get("identifier") or "")))
        values.add(normalize_vehicle_identifier(str(data.get("identifier_raw") or "")))
    return {value for value in values if value}


def _display_identifier(order):
    vehicle = order.allocated_vehicle
    if vehicle:
        return vehicle.identifier
    snapshot = getattr(order, "legacy_snapshot", None)
    return snapshot.vehicle_identifier if snapshot else ""


def build_plan(mapping, lock=False):
    """回傳 (每張單的預覽列, 車色計畫)；lock=True 時鎖住訂單與車色（--apply 用）。"""
    orders = SalesOrder.objects.select_related(
        "vehicle_model", "color", "allocated_vehicle__color", "legacy_snapshot__import_row",
    ).order_by("pk")
    if lock:
        orders = orders.select_for_update(of=("self",))
    rows, plans = [], {}
    for order in orders:
        model = order.vehicle_model
        row = {
            "order": order, "skip": "", "plan": None,
            "values": {
                "訂單編號": order.number, "訂單ID": order.pk, "訂單狀態": order.get_status_display(),
                "品牌": model.brand, "車型": model.name, "型號": model.model_number, "年式": model.model_year or "",
                "引擎／車身號碼": _display_identifier(order), "原車色": order.color.label,
                "新車色": "", "色碼": "", "車色處理": "", "結果": "略過", "略過原因": "",
                "已配庫存車車色": "",
            },
        }
        rows.append(row)
        if _key(model.brand) not in SUZUKI_BRANDS:
            row["skip"] = "非台鈴品牌"
            continue
        identifiers = order_identifiers(order)
        if not identifiers:
            row["skip"] = "訂單沒有引擎／車身號碼"
            continue
        entries = set().union(*(mapping.get(ident, set()) for ident in identifiers))
        if not entries:
            row["skip"] = "對應表查無此號碼"
            continue
        model_text = _key(f"{model.brand} {model.name}")
        entries = {entry for entry in entries if entry[0] in {"", model_text}}
        if not entries:
            row["skip"] = "車型與對應表不符"
            continue
        # 號碼更正過的單可能同時對到舊號碼的空白列與新號碼的有效列；有有效列就不看空白列。
        entries = {entry for entry in entries if entry[1] and entry[2]} or entries
        targets = {(code, name) for _, code, name in entries}
        if len(targets) > 1:
            row["skip"] = "對應表同一號碼有多種色碼：" + "、".join(sorted(f"{n} {c}".strip() for c, n in targets))
            continue
        code, name = targets.pop()
        if not code or not name:
            row["skip"] = "查無色碼" if not code else "查無廣告色"
            continue
        plan = plans.setdefault((model.pk, _key(name)), ColorPlan(model.pk, name, code))
        plan.orders.append(row)
        row["plan"] = plan
        if plan.code != code:
            plan.skip = "同車型同廣告色有多個色碼"
            plan.code = "、".join(sorted({*plan.code.split("、"), code}))

    existing = VehicleColor.objects.filter(vehicle_model_id__in={key[0] for key in plans})
    if lock:
        existing = existing.select_for_update()
    by_key = {(color.vehicle_model_id, _key(color.name)): color for color in existing}
    for key, plan in plans.items():
        plan.existing = by_key.get(key)
        if plan.skip:
            plan.skip = f"{plan.skip}（{plan.code}）"
            continue
        if plan.existing is None:
            plan.action = "新建（停用）"
        elif not plan.existing.code:
            plan.action = "沿用（補色碼）"
        elif plan.existing.code.upper() == plan.code:
            plan.action = "沿用"
        else:
            plan.skip = f"同名車色已有其他色碼 {plan.existing.code}"

    for row in rows:
        plan, values, order = row["plan"], row["values"], row["order"]
        if plan:
            values["新車色"] = plan.existing.name if plan.existing else plan.name
            values["色碼"] = plan.code
            values["車色處理"] = plan.action
            row["skip"] = row["skip"] or plan.skip
        if row["skip"]:
            values["略過原因"] = row["skip"]
            continue
        on_target = plan.existing is not None and plan.action == "沿用"
        new_label = f"{values['新車色']} {plan.code}"
        row["order_change"] = not (on_target and order.color_id == plan.existing.pk)
        vehicle = order.allocated_vehicle
        row["vehicle_change"] = bool(vehicle) and not (on_target and vehicle.color_id == plan.existing.pk)
        if vehicle:
            values["已配庫存車車色"] = f"{vehicle.color.label}→{new_label}" if row["vehicle_change"] else "已是新車色"
        values["結果"] = "更新" if row["order_change"] or row["vehicle_change"] else "不變"
    return rows, plans


def write_preview(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PREVIEW_HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row["values"])
    return path


def apply_plan(rows, plans):
    now = timezone.now()
    created = filled = changed = 0
    for plan in plans.values():
        if plan.skip or not any(row["values"]["結果"] == "更新" for row in plan.orders):
            continue
        if plan.existing is None:
            plan.existing = VehicleColor.objects.create(
                vehicle_model_id=plan.vehicle_model_id, name=plan.name, code=plan.code, active=False,
            )
            created += 1
        elif not plan.existing.code:
            VehicleColor.objects.filter(pk=plan.existing.pk).update(code=plan.code, updated_at=now)
            plan.existing.code = plan.code
            filled += 1
    pending = [row for row in rows if row["values"]["結果"] == "更新"]
    vehicle_ids = [row["order"].allocated_vehicle_id for row in pending if row["vehicle_change"]]
    vehicles = VehicleInventory.objects.select_for_update(of=("self",)).select_related(
        "color", "location_store", "current_dealer").in_bulk(vehicle_ids)
    vehicles_changed = 0
    for row in pending:
        order, color = row["order"], row["plan"].existing
        changes = {}
        if row["order_change"]:
            if order.color_id != color.pk:
                SalesOrder.all_objects.filter(pk=order.pk).update(color=color, updated_at=now)
            changes["車色"] = {"before": order.color.label, "after": color.label}
        vehicle = vehicles.get(order.allocated_vehicle_id) if row["vehicle_change"] else None
        if vehicle is not None:
            before = vehicle.color.label
            if vehicle.color_id != color.pk:
                VehicleInventory.objects.filter(pk=vehicle.pk).update(color=color, updated_at=now)
            # 已配庫存車與訂單同一交易改成同一個車色，庫存異動紀錄留痕（使用者 2026-11-17 選 A）。
            VehicleInventoryHistory.objects.create(
                vehicle=vehicle, event_type=VehicleInventoryHistory.EventType.UPDATED, actor_name=ACTOR,
                reason=f"{REASON}（隨訂單 {order.number}）", changes={"車色": {"before": before, "after": color.label}},
                status_snapshot=vehicle.status, location_store_snapshot=vehicle.location_store,
                location_label_snapshot=vehicle.actual_location_label, condition_note_snapshot=vehicle.condition_note,
                condition_resolution_snapshot=vehicle.condition_resolution,
            )
            changes["已配庫存車車色"] = {"before": before, "after": color.label}
            vehicles_changed += 1
        # 建立 OrderChange 會排程重建搜尋索引，訂單搜尋即可用新車色與色碼找到。
        OrderChange.objects.create(order=order, actor_name=ACTOR, reason=REASON, changes=changes)
        changed += 1
    return created, filled, changed, vehicles_changed


class Command(BaseCommand):
    help = "依原廠色碼表把訂單車色更正為「廣告色＋色碼」；預設 dry-run，--apply 才寫入。"

    def add_arguments(self, parser):
        parser.add_argument("mapping", help="對應表 xlsx／csv（車型、引擎號碼、顏色代碼、廣告色）")
        parser.add_argument("--apply", action="store_true", help="實際寫入（預設只預覽）")
        parser.add_argument("--output", default="apply_color_codes_preview.csv", help="預覽 CSV 路徑")

    def handle(self, *args, **options):
        mapping = read_mapping(options["mapping"])
        if options["apply"]:
            with transaction.atomic():
                rows, plans = build_plan(mapping, lock=True)
                created, filled, changed, vehicles_changed = apply_plan(rows, plans)
        else:
            rows, plans = build_plan(mapping)
        path = write_preview(options["output"], rows)
        results = Counter(row["values"]["結果"] for row in rows)
        skipped = Counter(row["values"]["略過原因"] for row in rows if row["values"]["略過原因"])
        actions = Counter(plan.action for plan in plans.values()
                          if not plan.skip and any(r["values"]["結果"] == "更新" for r in plan.orders))
        vehicle_updates = sum(1 for row in rows if row["values"]["結果"] == "更新" and row.get("vehicle_change"))
        self.stdout.write(f"訂單 {len(rows)} 張：更新 {results['更新']}、不變 {results['不變']}、略過 {results['略過']}")
        self.stdout.write("車色：" + ("、".join(f"{name} {count} 個" for name, count in actions.most_common()) or "無需建立或補色碼"))
        for reason, count in skipped.most_common():
            self.stdout.write(f"  略過（{reason}）：{count}")
        self.stdout.write(f"已配庫存車要一起改車色：{vehicle_updates} 台")
        self.stdout.write(f"預覽 CSV：{path}")
        if not options["apply"]:
            self.stdout.write("dry-run：未寫入。加上 --apply 才會寫入。")
            return
        self.stdout.write(self.style.SUCCESS(
            f"完成：新建車色 {created} 個、補色碼 {filled} 個、更新訂單 {changed} 張（每張留 OrderChange）、"
            f"已配庫存車 {vehicles_changed} 台（每台留庫存異動紀錄）。"))
