"""依使用者逐筆指定的類別，歸類配件主檔（使用者 2026-11-13 T-153 做法乙：不刪除主檔、直接改類別）。

正式資料寫入，使用者逐筆同意，只限這一次。用名稱比對（不依賴 id），訂單配件明細不動、仍連在主檔。

- 預設 dry-run：逐筆列出「名稱｜目前類別｜改後類別｜變更」，以及不在清單上的主檔、清單上找不到的名稱。
- --export：只輸出 JSON 備份到 stdout（每筆主檔的目前類別），在主機上導到檔案保存。
- --apply：同一交易內改類別、新增「前側保桿」，逐筆印出改前→改後；清單上的名稱找不到就整筆不做。
- --restore：從 stdin 讀 --export 的 JSON，把類別改回去；本指令新增、且沒有訂單用到的「前側保桿」一併刪除。
"""
import json
import sys
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from sales.models import AccessoryCategory, AccessoryLine, AccessoryProduct

PLAN = {
    "安全帽": ["輕便安全帽"],
    "手機架": ["五匹手機架"],
    "保桿": ["前土除保桿", "左右前側保桿", "左右後側保桿"],
    "改裝部品": ["刀鋒燈罩", "原廠踩發桿", "增高螺絲", "方向燈框", "腳踏飛翼", "風鏡", "SUI 後貨架", "SUI 日規後貨架",
                 "SUI 黑鐵書包架", "小偉士後貨架", "SIXIS後貨架", "CCD C03 後避震", "GHOST小圓鏡", "NCY N-17 SUI 前叉組",
                 "輪框改色 (金色)", "兒童座椅", "前側保桿"],
    "行車紀錄器": ["MS206行車紀錄器", "MS283WGS"],
    "原廠配件": ["Saluto 遙控鑰匙"],
    "其他": ["SHAD 33L"],
}
# 主檔原本沒有、使用者指定新增的名稱（舊單上的自填加購列已有這個名稱）。
NEW_NAMES = {"前側保桿"}
NOTE = "T-153 使用者 2026-11-13 指定歸類時新增（assign_accessory_categories）"


def target_of():
    return {name: category for category, names in PLAN.items() for name in names}


def find(name):
    return AccessoryProduct.objects.filter(name__iexact=name).select_related("category").first()


def label(category):
    return category.name if category else "未分類"


class Command(BaseCommand):
    help = "依使用者指定歸類配件主檔：預設 dry-run；--export 備份；--apply 寫入；--restore 從備份改回。"

    def add_arguments(self, parser):
        parser.add_argument("--export", action="store_true", help="只輸出 JSON 備份到 stdout")
        parser.add_argument("--apply", action="store_true", help="實際寫入（預設只列出）")
        parser.add_argument("--restore", action="store_true", help="從 stdin 讀 --export 的 JSON 改回")

    def handle(self, *args, **options):
        if options["export"]:
            data = {item.name: label(item.category) for item in AccessoryProduct.objects.select_related("category").order_by("pk")}
            self.stdout.write(json.dumps(data, ensure_ascii=False, indent=1))
            return
        if options["restore"]:
            return self.restore(json.load(sys.stdin))
        categories = {item.name: item for item in AccessoryCategory.objects.all()}
        missing_categories = sorted(set(PLAN) - set(categories))
        if missing_categories:
            raise CommandError("找不到類別：" + "、".join(missing_categories) + "（先套用 migration 0205）")
        targets = target_of()
        missing = [name for name in targets if name not in NEW_NAMES and find(name) is None]
        changed = 0
        for name, category in targets.items():
            product = find(name)
            before = label(product.category) if product else "（新增）"
            mark = "新增" if product is None else ("變更" if before != category else "不變")
            changed += mark != "不變"
            self.stdout.write(f"{name}｜{before}｜{category}｜{mark}")
        planned = {name.casefold() for name in targets}
        others = AccessoryProduct.objects.exclude(name__in=[name for name in targets]).select_related("category")
        others = [item for item in others if item.name.casefold() not in planned]
        self.stdout.write(f"清單 {len(targets)} 筆，需寫入 {changed} 筆；不在清單上的主檔 {len(others)} 筆"
                          + ("：" + "、".join(f"{item.name}（{label(item.category)}）" for item in others) if others else ""))
        if missing:
            self.stdout.write(self.style.ERROR("清單上找不到的主檔：" + "、".join(missing)))
        if not options["apply"]:
            self.stdout.write("dry-run：未變更。先用 --export 備份，再加 --apply 執行。")
            return
        if missing:
            raise CommandError("清單上有主檔找不到，未寫入。")
        linked_before = AccessoryLine.objects.filter(accessory_product__isnull=False).count()
        with transaction.atomic():
            list(AccessoryProduct.objects.select_for_update().order_by("pk"))
            for name, category_name in targets.items():
                category = categories[category_name]
                product = find(name)
                if product is None:
                    first = (AccessoryLine.objects.filter(name=name, accessory_product__isnull=True,
                                                          line_type=AccessoryLine.LineType.PURCHASE).order_by("pk").first())
                    AccessoryProduct.objects.create(name=name, category=category, note=NOTE,
                                                    sale_price=first.amount if first else Decimal("0"),
                                                    labor_fee=first.labor_fee if first else Decimal("0"))
                    self.stdout.write(f"新增 {name}：→ {category_name}")
                elif product.category_id != category.pk:
                    self.stdout.write(f"變更 {name}：{label(product.category)} → {category_name}")
                    product.category = category
                    product.save(update_fields=["category", "updated_at"])
            leftover = [name for name in targets if label(find(name).category) != targets[name]]
            if leftover or AccessoryLine.objects.filter(accessory_product__isnull=False).count() != linked_before:
                raise CommandError("寫入後檢查不符，已全部復原。")
        uncategorised = AccessoryProduct.objects.filter(category__isnull=True).count()
        self.stdout.write(self.style.SUCCESS(
            f"完成：{len(targets)} 筆都在指定類別；未分類主檔 {uncategorised} 筆；連到主檔的訂單明細 {linked_before} 列不變。"))

    def restore(self, data):
        categories = {item.name: item for item in AccessoryCategory.objects.all()}
        with transaction.atomic():
            for name, category_name in data.items():
                product = find(name)
                if product is None:
                    continue
                category = categories.get(category_name)
                if product.category_id != getattr(category, "pk", None):
                    self.stdout.write(f"改回 {name}：{label(product.category)} → {label(category)}")
                    product.category = category
                    product.save(update_fields=["category", "updated_at"])
            for name in NEW_NAMES - set(data):
                product = find(name)
                if product and product.note == NOTE and not product.order_lines.exists():
                    product.delete()
                    self.stdout.write(f"刪除本指令新增的 {name}")
        self.stdout.write(self.style.SUCCESS("還原完成。"))
