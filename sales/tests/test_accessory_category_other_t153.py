"""使用者 2026-11-12 T-153：配件類別「乘載」改名為「其他」，掛在底下的配件跟著走、不遺失。"""
import importlib
from decimal import Decimal

from django.apps import apps
from django.test import TestCase

from sales.forms import AccessoryLineForm
from sales.models import AccessoryCategory, AccessoryProduct

migration = importlib.import_module("sales.migrations.0205_rename_accessory_category_other")


class AccessoryCategoryOtherTests(TestCase):
    def reset_to_old_name(self):
        # 測試資料庫已套用 0205；先還原成正式站改名前的狀態（0199 建立的「乘載」）。
        AccessoryCategory.objects.filter(name="其他").update(name="乘載")
        old = AccessoryCategory.objects.get(name="乘載")
        seat = AccessoryProduct.objects.create(name="兒童座椅", category=old, sale_price=Decimal("500"))
        return old, seat

    def test_migrated_category_list_has_other_instead_of_carrying(self):
        names = list(AccessoryCategory.objects.values_list("name", flat=True))
        self.assertIn("其他", names)
        self.assertNotIn("乘載", names)
        self.assertEqual(names[-1], "其他")
        options = str(AccessoryLineForm()["accessory_category"])
        self.assertIn(">其他</option>", options)
        self.assertNotIn("乘載", options)

    def test_rename_keeps_products_and_is_reversible(self):
        old, seat = self.reset_to_old_name()
        migration.rename_to_other(apps, None)
        old.refresh_from_db()
        seat.refresh_from_db()
        self.assertEqual((old.name, old.active, old.sort_order), ("其他", True, 70))
        self.assertEqual(seat.category, old)
        migration.rename_to_other(apps, None)  # 重跑不出錯、不重複
        self.assertEqual(AccessoryCategory.objects.filter(name="其他").count(), 1)
        migration.rename_back(apps, None)
        old.refresh_from_db()
        self.assertEqual(old.name, "乘載")
        self.assertEqual(AccessoryProduct.objects.get(pk=seat.pk).category, old)

    def test_existing_other_category_receives_products(self):
        old, seat = self.reset_to_old_name()
        other = AccessoryCategory.objects.create(name="其他", sort_order=80)
        migration.rename_to_other(apps, None)
        old.refresh_from_db()
        seat.refresh_from_db()
        self.assertEqual(seat.category, other)
        self.assertFalse(old.active)
        self.assertEqual(old.name, "乘載")
