"""使用者 2026-11-12／11-13 T-153：配件類別固定 7 類；在類別內新增的配件名稱只儲存在該類別。"""
import importlib
from decimal import Decimal

from django.apps import apps
from django.test import TestCase, override_settings
from django.urls import reverse

from sales.forms import AccessoryLineForm
from sales.models import AccessoryCategory, AccessoryLine, AccessoryProduct, SalesOrder
from sales.tests import test_order_lifecycle as lifecycle
from sales.tests import test_order_wizard

migration = importlib.import_module("sales.migrations.0205_fixed_accessory_categories")


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


class AccessoryCategoryFixedTests(TestCase):
    SEVEN = ["安全帽", "手機架", "行車紀錄器", "保桿", "改裝部品", "原廠配件", "其他"]

    def test_migrated_categories_are_the_fixed_seven(self):
        self.assertEqual(list(AccessoryCategory.objects.values_list("name", flat=True)), self.SEVEN)
        options = str(AccessoryLineForm()["accessory_category"])
        for old in ("乘載", "後貨架／置物", "電子與鑰匙", "外觀改裝"):
            self.assertNotIn(old, options)

    def test_custom_name_option_no_longer_reads_other(self):
        # 使用者 2026-11-13 同意：類別有了「其他」，名稱選單的自填選項改叫「自行填寫名稱」，值仍是 other。
        options = str(AccessoryLineForm()["accessory_product"])
        self.assertIn('<option value="other">自行填寫名稱</option>', options)
        self.assertNotIn("其他（自行填寫名稱）", options)

    def test_fix_keeps_renamed_products_and_is_reversible(self):
        # 回到 0199 的狀態（正式站目前的樣子），每個舊類別放一個配件。
        migration.restore_categories(apps, None)
        old = {c.name: c for c in AccessoryCategory.objects.all()}
        self.assertEqual(list(old), ["安全帽", "手機架", "後貨架／置物", "保桿", "外觀改裝", "電子與鑰匙", "乘載"])
        products = {name: AccessoryProduct.objects.create(name=item, category=old[name])
                    for name, item in [("乘載", "兒童座椅"), ("電子與鑰匙", "MS206行車紀錄器"),
                                       ("外觀改裝", "風鏡"), ("後貨架／置物", "SHAD 33L"), ("安全帽", "輕便安全帽")]}
        migration.fix_categories(apps, None)
        migration.fix_categories(apps, None)  # 重跑結果一樣
        self.assertEqual(list(AccessoryCategory.objects.values_list("name", flat=True)), self.SEVEN)
        moved = {name: AccessoryProduct.objects.get(pk=item.pk).category for name, item in products.items()}
        self.assertEqual(moved["乘載"].pk, old["乘載"].pk)  # 原地改名，類別 id 不變
        self.assertEqual(moved["乘載"].name, "其他")
        self.assertEqual(moved["電子與鑰匙"].name, "行車紀錄器")
        self.assertEqual(moved["外觀改裝"].name, "改裝部品")
        self.assertEqual(moved["安全帽"].name, "安全帽")
        self.assertIsNone(moved["後貨架／置物"])  # 類別刪除，配件留著（之後由 assign_accessory_categories 歸類）
        migration.restore_categories(apps, None)
        self.assertEqual(list(AccessoryCategory.objects.values_list("name", flat=True)),
                         ["安全帽", "手機架", "後貨架／置物", "保桿", "外觀改裝", "電子與鑰匙", "乘載"])
        self.assertEqual(AccessoryProduct.objects.get(name="兒童座椅").category.name, "乘載")

    def test_existing_target_category_receives_products(self):
        migration.restore_categories(apps, None)
        other = AccessoryCategory.objects.create(name="其他", sort_order=80)
        seat = AccessoryProduct.objects.create(name="兒童座椅", category=AccessoryCategory.objects.get(name="乘載"))
        migration.fix_categories(apps, None)
        self.assertEqual(AccessoryProduct.objects.get(pk=seat.pk).category, other)
        self.assertFalse(AccessoryCategory.objects.filter(name="乘載").exists())


class CustomNameCategoryRuleTests(TestCase):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def test_custom_name_needs_one_of_the_fixed_categories(self):
        # 使用者 2026-11-13：在「全部類別」選自行填寫名稱，要從 7 類選一個，不能存成未分類。
        data = {"accessory_category": "", "accessory_product": "other", "custom_name": "雨衣", "quantity": "1",
                "line_type": "purchase", "amount": "200", "labor_fee": "0", "note": ""}
        form = AccessoryLineForm(data, allow_manual=True)
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["accessory_category"], ["自行填寫名稱要先選類別，名稱會存進這個類別。"])
        other = AccessoryCategory.objects.get(name="其他")
        self.assertTrue(AccessoryLineForm({**data, "accessory_category": str(other.pk)}, allow_manual=True).is_valid())
        # 既有自填列（明細不存類別）沒改名稱就照樣能存，不會因為這條規則擋住舊訂單；改了名稱才要選類別。
        order, _vehicle = self.make_order()
        line = AccessoryLine.objects.create(order=order, name="雨衣", amount=Decimal("200"))
        self.assertTrue(AccessoryLineForm({**data, "quantity": "2"}, instance=line, allow_manual=True).is_valid())
        renamed = AccessoryLineForm({**data, "custom_name": "輕便雨衣"}, instance=line, allow_manual=True)
        self.assertFalse(renamed.is_valid())
        self.assertIn("accessory_category", renamed.errors)
