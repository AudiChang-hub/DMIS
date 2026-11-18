"""依原廠色碼對應表把庫存車改指到有色碼的車色（T-229，使用者 2026-11-18：「要補」，方案 A）。

T-223 的 apply_color_codes 只改訂單與已配庫存車；Excel 進貨匯入的歷史庫存車（已售出／已調出居多）
仍指到沒有色碼的通用色。本指令用同一份對應表（T-223 v5：車型、引擎／車身號碼、顏色代碼、廣告色），
以庫存車的引擎號碼或車身號碼比對，把車色改指到「同車型、同色碼」的既有車色。

- 只處理 SUZUKI、eReady；不新建車色、不改車色主檔（名稱、色碼、啟用都不動）。
- 目標車色依**執行當下**的車色主檔判斷（T-227 寫入後才跑，官網名稱優先）：
  1. 同車型只有一個車色是這個色碼 → 用它。
  2. 有多個 → 只有一個啟用中的就用它（T-227 後官網名稱色啟用、目錄名稱色停用）。
  3. 還是多個 → 用被訂單／庫存車指到最多次的那個（T-227 已把同色碼的單和車統一到官網名稱色）；
     平手就略過並列出候選。
- 略過：非台鈴、沒有號碼、對應表查無此號碼、車型不符、同號碼多種色碼、車型沒有這個色碼的車色、
  現車色已有不同色碼、已配訂單且訂單車色不是目標車色（交給訂單流程處理）。
- 預設 dry-run，只輸出預覽 CSV 與統計（每種改法幾台、比對不到的清單）；--apply 在同一交易內鎖住庫存車寫入，
  每台留一筆庫存異動紀錄。冪等：已指到目標車色的列為「不變」。
"""
import csv
from collections import Counter
from functools import partial
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from sales.management.commands.apply_color_codes import SUZUKI_BRANDS, _key, read_mapping
from sales.models import SalesOrder, VehicleColor, VehicleInventory, VehicleInventoryHistory

ACTOR = "PM（使用者指示）"
REASON = "T-229 依原廠色碼表把庫存車改指到有色碼的車色"
NOT_FOUND = "對應表查無此號碼"
PREVIEW_HEADERS = [
    "庫存ID", "狀態", "品牌", "車型", "型號", "年式", "引擎號碼", "車身號碼",
    "原車色", "新車色", "對應表廣告色", "色碼", "結果", "略過原因", "已配訂單",
]


def _usage_counts(color_ids):
    usage = Counter()
    for field_rows in (
        SalesOrder.all_objects.filter(color_id__in=color_ids).values("color_id").annotate(total=Count("id")),
        VehicleInventory.objects.filter(color_id__in=color_ids).values("color_id").annotate(total=Count("id")),
    ):
        for row in field_rows:
            usage[row["color_id"]] += row["total"]
    return usage


def resolve_target(candidates, usage):
    """candidates 是同車型、同色碼的車色；無法唯一判斷時回傳 None。"""
    if len(candidates) <= 1:
        return candidates[0] if candidates else None
    active = [color for color in candidates if color.active]
    if len(active) == 1:
        return active[0]
    ranked = sorted(active or candidates, key=lambda color: (-usage[color.pk], color.pk))
    return ranked[0] if usage[ranked[0].pk] > usage[ranked[1].pk] else None


def _skip(row, kind, detail=""):
    row["kind"] = kind
    row["values"]["略過原因"] = f"{kind}：{detail}" if detail else kind


def build_plan(mapping, lock=False):
    vehicles = VehicleInventory.objects.filter(
        Q(vehicle_model__brand__iexact="SUZUKI") | Q(vehicle_model__brand__iexact="eReady")
    ).select_related("vehicle_model", "color", "location_store", "current_dealer").order_by("pk")
    if lock:
        vehicles = vehicles.select_for_update(of=("self",))
    vehicles = [vehicle for vehicle in vehicles if _key(vehicle.vehicle_model.brand) in SUZUKI_BRANDS]
    model_ids = {vehicle.vehicle_model_id for vehicle in vehicles}
    coded = {}
    for color in VehicleColor.objects.filter(vehicle_model_id__in=model_ids).exclude(code="").order_by("pk"):
        coded.setdefault((color.vehicle_model_id, color.code.strip().upper()), []).append(color)
    usage = _usage_counts([color.pk for colors in coded.values() for color in colors])
    orders = {
        order.allocated_vehicle_id: order
        for order in SalesOrder.all_objects.filter(allocated_vehicle_id__in=[vehicle.pk for vehicle in vehicles])
        .select_related("color")
    }
    rows = []
    for vehicle in vehicles:
        model = vehicle.vehicle_model
        order = orders.get(vehicle.pk)
        values = {
            "庫存ID": vehicle.pk, "狀態": vehicle.get_status_display(), "品牌": model.brand, "車型": model.name,
            "型號": model.model_number, "年式": model.model_year or "", "引擎號碼": vehicle.engine_number,
            "車身號碼": vehicle.frame_number, "原車色": vehicle.color.label, "新車色": "", "對應表廣告色": "",
            "色碼": "", "結果": "略過", "略過原因": "", "已配訂單": order.number if order else "",
        }
        row = {"vehicle": vehicle, "target": None, "values": values, "kind": ""}
        rows.append(row)
        skip = partial(_skip, row)
        identifiers = {value for value in (vehicle.normalized_engine_number, vehicle.normalized_frame_number) if value}
        if not identifiers:
            skip("庫存車沒有引擎／車身號碼")
            continue
        entries = set().union(*(mapping.get(ident, set()) for ident in identifiers))
        if not entries:
            if (vehicle.color.code or "").strip():
                values["結果"] = "不變"  # 已有色碼，對應表沒列到也不用補。
            else:
                skip(NOT_FOUND)
            continue
        entries = {entry for entry in entries if entry[0] in {"", _key(f"{model.brand} {model.name}")}}
        if not entries:
            skip("車型與對應表不符")
            continue
        entries = {entry for entry in entries if entry[1] and entry[2]} or entries
        targets = {(code, name) for _, code, name in entries}
        if len(targets) > 1:
            skip("對應表同一號碼有多種色碼", "、".join(sorted(f"{n} {c}".strip() for c, n in targets)))
            continue
        code, name = targets.pop()
        values["色碼"], values["對應表廣告色"] = code, name
        if not code:
            skip("查無色碼")
            continue
        current_code = (vehicle.color.code or "").strip().upper()
        if current_code and current_code != code:
            skip("現車色已有其他色碼", f"{current_code}，對應表 {code}")
            continue
        candidates = coded.get((model.pk, code), [])
        target = resolve_target(candidates, usage)
        if target is None:
            if candidates:
                skip("同車型有多個同色碼車色無法判斷", "、".join(color.label for color in candidates))
            else:
                skip("車型沒有這個色碼的車色", f"{name} {code}")
            continue
        values["新車色"] = target.label
        if vehicle.color_id == target.pk:
            values["結果"] = "不變"
            continue
        if order and order.color_id != target.pk:
            skip("已配訂單且訂單車色不同，由訂單處理", f"{order.number} {order.color.label}")
            continue
        row["target"] = target
        values["結果"] = "更新"
    return rows


def write_preview(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PREVIEW_HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row["values"])
    return path


def apply_plan(rows):
    now = timezone.now()
    changed = 0
    for row in rows:
        target = row["target"]
        if target is None:
            continue
        vehicle = row["vehicle"]
        before = vehicle.color.label
        VehicleInventory.objects.filter(pk=vehicle.pk).update(color=target, updated_at=now)
        VehicleInventoryHistory.objects.create(
            vehicle=vehicle, event_type=VehicleInventoryHistory.EventType.UPDATED, actor_name=ACTOR, reason=REASON,
            changes={"車色": {"before": before, "after": target.label}},
            status_snapshot=vehicle.status, location_store_snapshot=vehicle.location_store,
            location_label_snapshot=vehicle.actual_location_label, condition_note_snapshot=vehicle.condition_note,
            condition_resolution_snapshot=vehicle.condition_resolution,
        )
        changed += 1
    return changed


class Command(BaseCommand):
    help = "依原廠色碼表把台鈴庫存車改指到同車型、同色碼的車色；預設 dry-run，--apply 才寫入。"

    def add_arguments(self, parser):
        parser.add_argument("mapping", help="對應表 xlsx／csv（車型、引擎號碼、顏色代碼、廣告色），T-223 v5")
        parser.add_argument("--apply", action="store_true", help="實際寫入（預設只預覽）")
        parser.add_argument("--output", default="apply_inventory_color_codes_preview.csv", help="預覽 CSV 路徑")

    def handle(self, *args, **options):
        mapping = read_mapping(options["mapping"])
        if options["apply"]:
            with transaction.atomic():
                rows = build_plan(mapping, lock=True)
                changed = apply_plan(rows)
        else:
            rows = build_plan(mapping)
        path = write_preview(options["output"], rows)
        values = [row["values"] for row in rows]
        results = Counter(value["結果"] for value in values)
        self.stdout.write(
            f"台鈴庫存車 {len(values)} 台：更新 {results['更新']}、不變 {results['不變']}、略過 {results['略過']}"
        )
        changes = Counter(
            f"{value['品牌']} {value['車型']} {value['年式']}：{value['原車色']} → {value['新車色']}"
            for value in values if value["結果"] == "更新"
        )
        self.stdout.write(f"改法 {len(changes)} 種：")
        for change, count in sorted(changes.items()):
            self.stdout.write(f"  {change}：{count} 台")
        skipped = Counter(row["kind"] for row in rows if row["kind"])
        for reason, count in skipped.most_common():
            self.stdout.write(f"  略過（{reason}）：{count}")
        self.stdout.write(f"比對不到的清單（略過的 {results['略過']} 台）：")
        for row in rows:
            value = row["values"]
            if row["kind"]:
                self.stdout.write(
                    f"  #{value['庫存ID']} {value['狀態']} {value['車型']} {value['年式']} "
                    f"{value['引擎號碼'] or value['車身號碼']} {value['原車色']}｜{value['略過原因']}"
                )
        self.stdout.write(f"預覽 CSV：{path}")
        if not options["apply"]:
            self.stdout.write("dry-run：未寫入。加上 --apply 才會寫入。")
            return
        self.stdout.write(self.style.SUCCESS(f"完成：庫存車改指車色 {changed} 台（每台留庫存異動紀錄）。"))
