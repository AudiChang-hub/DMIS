"""依使用者確認的計畫，把台鈴車色的啟用狀態對齊原廠官網（T-227，使用者 2026-11-18「都照建議」）。

計畫檔是 CSV（第一列為標題），一列一個車色：
  車型ID、車型（品牌 車型 型號 年式，用來核對 ID 沒填錯）、車色、新建（是／空白）、
  啟用（是／否／空白＝不動）、色碼（空白＝不動）、照片來源（同車型另一個車色）、統一到（同車型另一個車色）。
另可用 --vehicles 指定庫存車改色 CSV：引擎／車身號碼、車型ID、改成車色。

- 預設 dry-run：不寫入，輸出預覽 CSV 與統計；--apply 時整批在同一個交易內寫入。
- 「統一到」：這個車色上的訂單和庫存車（不論狀態）全部改到目標車色（使用者 2026-11-18：官網名稱與目錄名稱
  確認同色時統一到官網名稱，例如雙黑 YVB → 亮光黑 YVB）。每張訂單一筆 OrderChange、每台庫存車一筆庫存異動紀錄。
- 「照片來源」：把來源車色的展示照片搬到這個車色（來源清空）；車色主檔沒有稽核表，以預覽／結果 CSV 為紀錄。
- 只處理 SUZUKI、eReady；計畫有任何錯誤（車型對不上、車色不存在、色碼衝突、啟用中的車型會沒有啟用色…）就整批不寫。
- 冪等：已經是目標狀態的列為「不變」，再跑一次不會重複寫入。
"""
import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from sales.models import (
    OrderChange, SalesOrder, VehicleColor, VehicleInventory, VehicleInventoryHistory, VehicleModel,
    normalize_vehicle_identifier,
)

ACTOR = "PM（使用者指示）"
REASON = "T-227 車色啟用狀態對齊原廠官網，目錄名稱色統一到官網名稱"
SUZUKI_BRANDS = {"suzuki", "eready"}
IN_STOCK = {
    VehicleInventory.Status.AVAILABLE, VehicleInventory.Status.RESERVED, VehicleInventory.Status.CONDITION_ISSUE,
}
PREVIEW_HEADERS = ["類別", "車型", "對象", "內容", "結果"]
COLOR_COLUMNS = {"model_id": "車型ID", "model": "車型", "name": "車色", "create": "新建", "active": "啟用",
                 "code": "色碼", "photo_from": "照片來源", "merge_into": "統一到"}
VEHICLE_COLUMNS = {"ident": "引擎／車身號碼", "model_id": "車型ID", "color": "改成車色"}


def _key(text):
    return " ".join(str(text or "").split()).casefold()


def model_text(model):
    return " ".join(str(part) for part in (model.brand, model.name, model.model_number, model.model_year or "") if part)


def _read_csv(path, columns, required):
    path = Path(path)
    if not path.exists():
        raise CommandError(f"找不到計畫檔：{path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [title for key, title in columns.items() if key in required and title not in (reader.fieldnames or [])]
        if missing:
            raise CommandError(f"{path.name} 缺少欄位：{'、'.join(missing)}")
        return [
            {key: str(row.get(title) or "").strip() for key, title in columns.items()}
            for row in reader if any(str(value or "").strip() for value in row.values())
        ]


def read_color_plan(path):
    return _read_csv(path, COLOR_COLUMNS, {"model_id", "name"})


def read_vehicle_plan(path):
    return _read_csv(path, VEHICLE_COLUMNS, set(VEHICLE_COLUMNS))


def _flag(value, field, errors, where):
    if value in ("", None):
        return None
    if value in ("是", "啟用", "Y", "y", "1", "true", "True"):
        return True
    if value in ("否", "停用", "N", "n", "0", "false", "False"):
        return False
    errors.append(f"{where}：「{field}」只能填 是／否（{value}）")
    return None


@dataclass
class Target:
    model: VehicleModel
    name: str
    color: VehicleColor | None
    create: bool = False
    active: bool | None = None
    code: str = ""
    photo_from: str = ""
    merge_into: str = ""


class Plan:
    """把計畫檔轉成要做的動作；errors 不為空時不可寫入。"""

    def __init__(self, color_rows, vehicle_rows=(), lock=False):
        self.lock = lock
        self.errors, self.warnings, self.preview = [], [], []
        self.targets = {}
        self.vehicle_moves = []
        self._load(color_rows, vehicle_rows)
        if not self.errors:
            self._check_active_models()

    # ---------- 讀取與檢查 ----------
    def _colors(self, model_ids):
        queryset = VehicleColor.objects.filter(vehicle_model_id__in=model_ids)
        if self.lock:
            queryset = queryset.select_for_update()
        colors = {}
        for color in queryset:
            colors[(color.vehicle_model_id, _key(color.name))] = color
        return colors

    def _load(self, color_rows, vehicle_rows):
        model_ids = set()
        for index, row in enumerate([*color_rows, *vehicle_rows], start=2):
            if not row["model_id"].isdigit():
                self.errors.append(f"第 {index} 列：車型ID 不是數字（{row['model_id']}）")
            else:
                model_ids.add(int(row["model_id"]))
        models = VehicleModel.objects.in_bulk(model_ids)
        self.colors = self._colors(list(models))
        for index, row in enumerate(color_rows, start=2):
            where = f"車色第 {index} 列"
            model = self._model(models, row, where)
            if model is None:
                continue
            key = (model.pk, _key(row["name"]))
            if key in self.targets:
                self.errors.append(f"{where}：{model_text(model)} 的「{row['name']}」重複出現")
                continue
            create = _flag(row["create"], "新建", self.errors, where)
            color = self.colors.get(key)
            if color is None and not create:
                self.errors.append(f"{where}：{model_text(model)} 沒有「{row['name']}」，要新建請在「新建」填是")
                continue
            code = "".join(row["code"].split()).upper()
            if color is not None and code and color.code and color.code.upper() != code:
                self.errors.append(f"{where}：{model_text(model)}「{color.name}」已有色碼 {color.code}，計畫是 {code}")
                continue
            self.targets[key] = Target(
                model=model, name=row["name"], color=color, create=bool(create) and color is None,
                active=_flag(row["active"], "啟用", self.errors, where), code=code,
                photo_from=row["photo_from"], merge_into=row["merge_into"],
            )
        for key, target in self.targets.items():
            for field in ("photo_from", "merge_into"):
                other = getattr(target, field)
                if not other:
                    continue
                other_key = (target.model.pk, _key(other))
                if other_key == key or (other_key not in self.colors and not self._created(other_key)):
                    title = COLOR_COLUMNS[field]
                    self.errors.append(f"{model_text(target.model)}「{target.name}」的{title}「{other}」在同車型找不到")
        for index, row in enumerate(vehicle_rows, start=2):
            where = f"庫存車第 {index} 列"
            model = self._model(models, row, where, check_text=False)
            if model is None:
                continue
            ident = normalize_vehicle_identifier(row["ident"])
            vehicles = VehicleInventory.objects.filter(
                Q(normalized_engine_number=ident) | Q(normalized_frame_number=ident), vehicle_model=model)
            if self.lock:
                vehicles = vehicles.select_for_update(of=("self",))
            vehicles = list(vehicles.select_related("color", "vehicle_model", "location_store", "current_dealer"))
            color_key = (model.pk, _key(row["color"]))
            if len(vehicles) != 1:
                self.errors.append(f"{where}：{model_text(model)} 找到 {len(vehicles)} 台號碼 {row['ident']} 的庫存車")
            elif color_key not in self.colors and not self._created(color_key):
                self.errors.append(f"{where}：{model_text(model)} 沒有車色「{row['color']}」")
            else:
                self.vehicle_moves.append((vehicles[0], color_key))

    def _created(self, key):
        target = self.targets.get(key)
        return bool(target and target.create)

    def _model(self, models, row, where, check_text=True):
        if not row["model_id"].isdigit():
            return None
        model = models.get(int(row["model_id"]))
        if model is None:
            self.errors.append(f"{where}：找不到車型ID {row['model_id']}")
            return None
        if _key(model.brand) not in SUZUKI_BRANDS:
            self.errors.append(f"{where}：{model_text(model)} 不是 SUZUKI／eReady，不處理")
            return None
        if check_text and row.get("model") and _key(row["model"]) != _key(model_text(model)):
            self.errors.append(f"{where}：車型ID {model.pk} 是「{model_text(model)}」，跟計畫的「{row['model']}」不符")
            return None
        return model

    def final_active(self, color):
        target = self.targets.get((color.vehicle_model_id, _key(color.name)))
        return color.active if target is None or target.active is None else target.active

    def _check_active_models(self):
        model_ids = {target.model.pk for target in self.targets.values()}
        for model in VehicleModel.objects.filter(pk__in=model_ids, active=True):
            existing = [color for (model_id, _), color in self.colors.items() if model_id == model.pk]
            created = [t for t in self.targets.values() if t.model.pk == model.pk and t.create and t.active]
            if not created and not any(self.final_active(color) for color in existing):
                self.errors.append(f"啟用中的車型「{model_text(model)}」照計畫會沒有任何啟用車色")
        for key, target in self.targets.items():
            color = target.color
            if color is None or target.active is not False or target.merge_into:
                continue
            stock = VehicleInventory.objects.filter(color=color, status__in=IN_STOCK).exclude(
                pk__in=[vehicle.pk for vehicle, _ in self.vehicle_moves])
            if stock.exists():
                self.warnings.append(
                    f"{model_text(target.model)}「{color.name}」停用後還有 {stock.count()} 台在庫車留在這個車色（配不出去）")

    # ---------- 動作 ----------
    def _row(self, kind, model, subject, content, changed):
        self.preview.append({"類別": kind, "車型": model_text(model), "對象": subject, "內容": content,
                             "結果": "更新" if changed else "不變"})
        return changed

    def _color(self, key):
        return self.colors.get(key)

    def run(self, apply=False):
        """回傳統計；apply=False 只產生預覽。"""
        if self.errors:
            raise CommandError("計畫有錯誤，未寫入：\n" + "\n".join(self.errors))
        stats = Counter()
        now = timezone.now()
        # 1. 新建、啟用／停用、色碼
        for key, target in self.targets.items():
            color = target.color
            if target.create:
                self._row("車色", target.model, target.name, f"新建（{'啟用' if target.active else '停用'}）{target.code}", True)
                stats["新建車色"] += 1
                if apply:
                    color = VehicleColor.objects.create(
                        vehicle_model=target.model, name=target.name, code=target.code, active=bool(target.active))
                    self.colors[key] = color
                    target.color = color
                continue
            updates = {}
            if target.active is not None:
                changed = color.active != target.active
                self._row("車色", target.model, color.label, "啟用" if target.active else "停用", changed)
                if changed:
                    updates["active"] = target.active
                    stats["啟用車色" if target.active else "停用車色"] += 1
            if target.code:
                changed = (color.code or "").upper() != target.code
                self._row("車色", target.model, color.name, f"色碼 {target.code}", changed)
                if changed:
                    updates["code"] = target.code
                    stats["補色碼"] += 1
            if apply and updates:
                VehicleColor.objects.filter(pk=color.pk).update(**updates, updated_at=now)
                for field, value in updates.items():
                    setattr(color, field, value)
        # 2. 照片搬移（來源清空）
        for key, target in self.targets.items():
            if not target.photo_from:
                continue
            source = self._color((target.model.pk, _key(target.photo_from)))
            color = target.color
            image = source.catalog_image.name if source.catalog_image else ""
            current = color.catalog_image.name if color is not None and color.catalog_image else ""
            if not image:
                self._row("照片", target.model, f"{target.photo_from}→{target.name}",
                          "已搬過" if current else "來源沒有照片", False)
                continue
            if current and current != image:
                raise CommandError(f"{model_text(target.model)}「{target.name}」已有其他照片，不覆蓋（來源「{source.name}」）")
            self._row("照片", target.model, f"{source.name}→{target.name}", image, True)
            stats["搬照片"] += 1
            if apply:
                VehicleColor.objects.filter(pk=color.pk).update(catalog_image=image, updated_at=now)
                VehicleColor.objects.filter(pk=source.pk).update(catalog_image="", updated_at=now)
                color.catalog_image.name = image
                source.catalog_image.name = ""
        # 3. 統一到：訂單與庫存車改到目標車色
        moves = []
        for key, target in self.targets.items():
            if not target.merge_into:
                continue
            source = target.color
            destination_key = (target.model.pk, _key(target.merge_into))
            orders = SalesOrder.all_objects.filter(color=source).select_related(
                "color", "vehicle_model", "allocated_vehicle__color")
            vehicles = VehicleInventory.objects.filter(color=source)
            if self.lock:
                orders = orders.select_for_update(of=("self",))
                vehicles = vehicles.select_for_update(of=("self",))
            for order in orders.order_by("pk"):
                moves.append(("order", order, destination_key, target))
            for vehicle in vehicles.select_related(
                    "color", "vehicle_model", "location_store", "current_dealer").order_by("pk"):
                moves.append(("vehicle", vehicle, destination_key, target))
        for vehicle, color_key in self.vehicle_moves:
            moves.append(("vehicle", vehicle, color_key, None))
        vehicle_moved_for = {}
        for kind, obj, destination_key, target in moves:
            destination = self._color(destination_key)
            model = obj.vehicle_model
            after = destination.label if destination else self.targets[destination_key].name
            if kind == "order":
                changed = destination is None or obj.color_id != destination.pk
                self._row("訂單", model, obj.number, f"{obj.color.label}→{after}", changed)
                if changed:
                    stats["訂單改色"] += 1
                    if apply:
                        before = obj.color.label
                        SalesOrder.all_objects.filter(pk=obj.pk).update(color=destination, updated_at=now)
                        changes = {"車色": {"before": before, "after": destination.label}}
                        vehicle = obj.allocated_vehicle
                        if vehicle is not None and vehicle.color_id == obj.color_id:
                            # 已配庫存車在同一個車色上，下面會一起改；訂單紀錄也寫明。
                            changes["已配庫存車車色"] = {"before": vehicle.color.label, "after": destination.label}
                            vehicle_moved_for[vehicle.pk] = obj.number
                        # 建立 OrderChange 會排程重建搜尋索引。
                        OrderChange.objects.create(order=obj, actor_name=ACTOR, reason=REASON, changes=changes)
                continue
            changed = destination is None or obj.color_id != destination.pk
            self._row("庫存車", model, obj.identifier, f"{obj.color.label}→{after}", changed)
            if not changed:
                continue
            stats["庫存車改色"] += 1
            if apply:
                before = obj.color.label
                VehicleInventory.objects.filter(pk=obj.pk).update(color=destination, updated_at=now)
                note = "依零件目錄查詢結果" if target is None else f"統一到官網名稱「{destination.name}」"
                order_number = vehicle_moved_for.get(obj.pk)
                VehicleInventoryHistory.objects.create(
                    vehicle=obj, event_type=VehicleInventoryHistory.EventType.UPDATED, actor_name=ACTOR,
                    reason=f"{REASON}（{note}{f'，隨訂單 {order_number}' if order_number else ''}）",
                    changes={"車色": {"before": before, "after": destination.label}},
                    status_snapshot=obj.status, location_store_snapshot=obj.location_store,
                    location_label_snapshot=obj.actual_location_label, condition_note_snapshot=obj.condition_note,
                    condition_resolution_snapshot=obj.condition_resolution,
                )
        stats["更新"] = sum(1 for row in self.preview if row["結果"] == "更新")
        return stats


def write_preview(path, plan):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PREVIEW_HEADERS)
        writer.writeheader()
        writer.writerows(plan.preview)
    return path


class Command(BaseCommand):
    help = "依確認過的計畫對齊台鈴車色的啟用狀態（官網優先）；預設 dry-run，--apply 才寫入。"

    def add_arguments(self, parser):
        parser.add_argument("plan", help="車色計畫 CSV（車型ID、車型、車色、新建、啟用、色碼、照片來源、統一到）")
        parser.add_argument("--vehicles", help="庫存車改色 CSV（引擎／車身號碼、車型ID、改成車色）")
        parser.add_argument("--apply", action="store_true", help="實際寫入（預設只預覽）")
        parser.add_argument("--output", default="align_color_activation_preview.csv", help="預覽 CSV 路徑")

    def handle(self, *args, **options):
        color_rows = read_color_plan(options["plan"])
        vehicle_rows = read_vehicle_plan(options["vehicles"]) if options.get("vehicles") else []
        if options["apply"]:
            with transaction.atomic():
                plan = Plan(color_rows, vehicle_rows, lock=True)
                stats = plan.run(apply=True)
        else:
            plan = Plan(color_rows, vehicle_rows)
            stats = plan.run()
        path = write_preview(options["output"], plan)
        order = ["新建車色", "啟用車色", "停用車色", "補色碼", "搬照片", "訂單改色", "庫存車改色"]
        self.stdout.write("、".join(f"{name} {stats[name]}" for name in order) + f"（要更新的項目共 {stats['更新']}）")
        for warning in plan.warnings:
            self.stdout.write(self.style.WARNING(f"注意：{warning}"))
        self.stdout.write(f"預覽 CSV：{path}")
        if not options["apply"]:
            self.stdout.write("dry-run：未寫入。加上 --apply 才會寫入。")
            return
        self.stdout.write(self.style.SUCCESS(
            "完成：同一交易寫入；訂單每張留 OrderChange、庫存車每台留庫存異動紀錄。"))
