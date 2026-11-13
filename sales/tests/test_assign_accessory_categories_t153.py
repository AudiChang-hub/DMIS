"""使用者 2026-11-13 T-153 做法乙：不刪除主檔，依逐筆指定改類別，再新增「前側保桿」。"""
import io
import json
import sys
from decimal import Decimal
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from sales.management.commands.assign_accessory_categories import NOTE, PLAN
from sales.models import AccessoryCategory, AccessoryLine, AccessoryProduct
from sales.services.accessory_catalog import learn_custom_accessories
from sales.tests import test_order_lifecycle as lifecycle

# 正式站 2026-11-13 套用 0205 後的樣子：後貨架／置物刪除（未分類）、外觀改裝→改裝部品、電子與鑰匙→行車紀錄器、乘載→其他。
BEFORE = {
    "輕便安全帽": "安全帽", "五匹手機架": "手機架", "前土除保桿": "保桿", "左右前側保桿": "保桿", "左右後側保桿": "保桿",
    "刀鋒燈罩": "改裝部品", "原廠踩發桿": "改裝部品", "增高螺絲": "改裝部品", "方向燈框": "改裝部品", "腳踏飛翼": "改裝部品",
    "風鏡": "改裝部品", "MS206行車紀錄器": "行車紀錄器", "Saluto 遙控鑰匙": "行車紀錄器", "兒童座椅": "其他",
    "SHAD 33L": None, "SUI 後貨架": None, "SUI 日規後貨架": None, "SUI 黑鐵書包架": None, "小偉士後貨架": None,
    "CCD C03 後避震": None, "GHOST小圓鏡": None, "MS283WGS": None, "NCY N-17 SUI 前叉組": None, "SIXIS後貨架": None,
    "輪框改色 (金色)": None,
}


class AssignAccessoryCategoriesTests(TestCase):
    setUp_base = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def setUp(self):
        self.setUp_base()
        self.order, _vehicle = self.make_order()
        categories = {item.name: item for item in AccessoryCategory.objects.all()}
        self.products = {name: AccessoryProduct.objects.create(name=name, category=categories.get(category), sale_price=Decimal("100"))
                         for name, category in BEFORE.items()}
        self.linked = AccessoryLine.objects.create(order=self.order, accessory_product=self.products["SUI 日規後貨架"],
                                                   name="SUI 日規後貨架", amount=Decimal("1200"))
        self.custom = AccessoryLine.objects.create(order=self.order, name="前側保桿", amount=Decimal("1500"), labor_fee=Decimal("200"))

    def run_command(self, *args, stdin=None):
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(stdin or "")):
            call_command("assign_accessory_categories", *args, stdout=out)
        return out.getvalue()

    def categories(self):
        return {item.name: (item.category.name if item.category_id else None)
                for item in AccessoryProduct.objects.select_related("category")}

    def test_plan_covers_every_existing_product_once(self):
        names = [name for names in PLAN.values() for name in names]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), set(BEFORE) | {"前側保桿"})
        self.assertEqual(set(PLAN), set(AccessoryCategory.objects.values_list("name", flat=True)))

    def test_dry_run_lists_changes_and_writes_nothing(self):
        before = self.categories()
        output = self.run_command()
        self.assertIn("SUI 後貨架｜未分類｜改裝部品｜變更", output)
        self.assertIn("Saluto 遙控鑰匙｜行車紀錄器｜原廠配件｜變更", output)
        self.assertIn("輕便安全帽｜安全帽｜安全帽｜不變", output)
        self.assertIn("前側保桿｜（新增）｜保桿｜新增", output)
        self.assertIn("清單 26 筆，需寫入 14 筆；不在清單上的主檔 0 筆", output)
        self.assertIn("dry-run：未變更", output)
        self.assertEqual(self.categories(), before)

    def test_apply_assigns_every_name_keeps_order_links_and_restore_undoes(self):
        backup = self.run_command("--export")
        self.assertEqual(json.loads(backup)["SUI 後貨架"], "未分類")
        output = self.run_command("--apply")
        self.assertIn("變更 兒童座椅：其他 → 改裝部品", output)
        self.assertIn("未分類主檔 0 筆", output)
        expected = {name: category for category, names in PLAN.items() for name in names}
        self.assertEqual(self.categories(), expected)
        counts = {name: list(self.categories().values()).count(name) for name in PLAN}
        self.assertEqual(counts, {"安全帽": 1, "手機架": 1, "保桿": 4, "改裝部品": 16, "行車紀錄器": 2, "原廠配件": 1, "其他": 1})
        new = AccessoryProduct.objects.get(name="前側保桿")
        self.assertEqual((new.sale_price, new.labor_fee, new.note), (Decimal("1500"), Decimal("200"), NOTE))
        self.assertEqual(new.category.name, "保桿")  # 使用者 2026-11-13 改指定到保桿
        self.linked.refresh_from_db()
        self.assertEqual(self.linked.accessory_product, self.products["SUI 日規後貨架"])  # 訂單明細仍連在主檔
        self.custom.refresh_from_db()
        self.assertIsNone(self.custom.accessory_product)  # 舊自填列照 2026-10-15 規則不改掛
        # 有加購列的名稱都在主檔了：舊單再存檔不會多出未分類。
        self.assertEqual(learn_custom_accessories(self.order, "測試"), [])
        self.assertFalse(AccessoryProduct.objects.filter(category__isnull=True).exists())
        self.run_command("--apply")  # 重跑不出錯、不重複新增
        self.assertEqual(AccessoryProduct.objects.filter(name="前側保桿").count(), 1)
        self.run_command("--restore", stdin=backup)
        self.assertEqual(self.categories(), BEFORE)

    def test_apply_refuses_when_a_listed_product_is_missing(self):
        self.products["風鏡"].delete()
        with self.assertRaises(CommandError):
            self.run_command("--apply")
        self.assertFalse(AccessoryProduct.objects.filter(name="前側保桿").exists())
