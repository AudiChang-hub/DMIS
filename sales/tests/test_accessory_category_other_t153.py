"""使用者 2026-11-12 T-153：配件類別「乘載」改名為「其他」，掛在底下的配件跟著走、不遺失；
2026-11-13：在類別內新增的配件名稱只儲存在該類別。"""
import importlib
from decimal import Decimal

from django.apps import apps
from django.test import TestCase, override_settings
from django.urls import reverse

from sales.forms import AccessoryLineForm
from sales.models import AccessoryCategory, AccessoryProduct, SalesOrder
from sales.tests import test_order_wizard

migration = importlib.import_module("sales.migrations.0205_rename_accessory_category_other")


@override_settings(MEDIA_ROOT=test_order_wizard.MEDIA)
class WizardCustomAccessoryCategoryTests(TestCase):
    setUp = test_order_wizard.OrderWizardTests.setUp
    image = test_order_wizard.OrderWizardTests.image
    complete_data = test_order_wizard.OrderWizardTests.complete_data
    post = test_order_wizard.OrderWizardTests.post
    draft = test_order_wizard.OrderWizardTests.draft
    walk_to = test_order_wizard.OrderWizardTests.walk_to

    def test_chosen_category_survives_later_steps_and_learns_into_it(self):
        helmet = AccessoryCategory.objects.get(name="安全帽")
        draft = self.walk_to("accessories")
        line = {"accessories-TOTAL_FORMS": "1", "accessories-INITIAL_FORMS": "0",
                "accessories-0-accessory_category": str(helmet.pk), "accessories-0-accessory_product": "other",
                "accessories-0-custom_name": "3/4安全帽", "accessories-0-quantity": "1",
                "accessories-0-line_type": "purchase", "accessories-0-amount": "1500", "accessories-0-labor_fee": "0"}
        self.assertEqual(self.post("accessories", draft=draft, **line).status_code, 302)
        # 換到下一步由草稿重新載入：選過的類別要還在，否則送出時「其他」名稱會歸到未分類。
        page = self.client.get(reverse("order_create"), {"draft": draft.pk, "step": "deposit"}).content.decode()
        select = page.split('name="accessories-0-accessory_category"', 1)[1].split("</select>", 1)[0]
        self.assertIn(f'<option value="{helmet.pk}" selected>安全帽</option>', select)
        self.assertEqual(self.post("deposit", draft=self.draft(), **line).status_code, 302)
        self.post("confirm", action="submit", draft=self.draft(), **line)
        self.assertTrue(SalesOrder.objects.filter(owner_name="測試車主").exists())
        self.assertEqual(AccessoryProduct.objects.get(name="3/4安全帽").category, helmet)


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

    def test_custom_name_option_no_longer_reads_other(self):
        # 使用者 2026-11-13 同意：類別有了「其他」，名稱選單的自填選項改叫「自行填寫名稱」，值仍是 other。
        options = str(AccessoryLineForm()["accessory_product"])
        self.assertIn('<option value="other">自行填寫名稱</option>', options)
        self.assertNotIn("其他（自行填寫名稱）", options)

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
