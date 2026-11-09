"""使用者 2026-11-09 T-138 p3 方案 A：配件「類別 → 名稱」兩層；「其他」自填名稱照 2026-10-15 規則自動加進主檔，
並歸到那一列選的類別；配件主檔可改類別、停用、合併。"""
import importlib
from decimal import Decimal

from django.apps import apps
from django.test import TestCase
from django.urls import reverse

from sales.forms import AccessoryLineForm
from sales.models import AccessoryCategory, AccessoryLine, AccessoryProduct
from sales.tests import test_order_lifecycle as lifecycle
from sales.tests import test_store_handles_orders as store


class AccessoryCategoryTests(TestCase):
    setUp_base = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def setUp(self):
        self.setUp_base()
        self.order, _vehicle = self.make_order()
        # migration 已建立提案表的類別
        self.helmet = AccessoryCategory.objects.get(name="安全帽")
        self.holder = AccessoryCategory.objects.get(name="手機架")
        self.light = AccessoryProduct.objects.create(name="輕便安全帽", category=self.helmet, sale_price=Decimal("800"))
        self.five = AccessoryProduct.objects.create(name="五匹手機架", category=self.holder, sale_price=Decimal("1200"))
        self.loose = AccessoryProduct.objects.create(name="風鏡", sale_price=Decimal("300"))

    def line_form(self, instance=None, allow_manual=False, **data):
        payload = {"accessory_category": "", "accessory_product": "", "custom_name": "", "quantity": "1",
                   "line_type": "purchase", "amount": "", "labor_fee": "", "note": ""}
        payload.update(data)
        return AccessoryLineForm(payload, instance=instance or AccessoryLine(order=self.order), allow_manual=allow_manual)

    def test_migration_plan_assigns_existing_products_only(self):
        AccessoryProduct.objects.create(name="SHAD 33L")
        AccessoryProduct.objects.create(name="兒童座椅")
        migration = importlib.import_module("sales.migrations.0199_accessory_categories")
        migration.assign_categories(apps, None)
        self.assertEqual(AccessoryProduct.objects.get(name="SHAD 33L").category.name, "後貨架／置物")
        self.assertEqual(AccessoryProduct.objects.get(name="兒童座椅").category.name, "乘載")
        self.assertEqual(AccessoryProduct.objects.get(name="風鏡").category.name, "外觀改裝")
        # 已有類別的不被覆蓋
        self.assertEqual(AccessoryProduct.objects.get(pk=self.light.pk).category, self.helmet)

    def test_names_are_grouped_by_category_with_uncategorised_last(self):
        html = str(self.line_form()["accessory_product"])
        self.assertLess(html.index('<optgroup label="安全帽">'), html.index('<optgroup label="手機架">'))
        self.assertLess(html.index('<optgroup label="手機架">'), html.index('<optgroup label="未分類">'))
        self.assertLess(html.index('<optgroup label="未分類">'), html.index('value="other"'))
        line = AccessoryLine.objects.create(order=self.order, accessory_product=self.five, name=self.five.name, amount=Decimal("1200"))
        self.assertEqual(AccessoryLineForm(instance=line).initial["accessory_category"], self.holder.pk)

    def test_learned_item_goes_to_the_chosen_category_and_keeps_old_rules(self):
        from types import SimpleNamespace
        from sales.services.accessory_catalog import custom_accessory_categories, learn_custom_accessories
        forms = [SimpleNamespace(cleaned_data={"custom_name": "  3/4安全帽 ", "accessory_category": self.helmet}),
                 SimpleNamespace(cleaned_data={"custom_name": "雨衣", "accessory_category": None}),
                 SimpleNamespace(cleaned_data={"custom_name": "刪掉的", "accessory_category": self.holder, "DELETE": True})]
        categories = custom_accessory_categories(SimpleNamespace(forms=forms))
        self.assertEqual(categories, {"3/4安全帽": self.helmet})
        line = AccessoryLine.objects.create(order=self.order, name="3/4安全帽", amount=Decimal("1500"))
        AccessoryLine.objects.create(order=self.order, name="雨衣", amount=Decimal("200"))
        self.assertEqual(learn_custom_accessories(self.order, "測試", categories=categories), ["3/4安全帽", "雨衣"])
        self.assertEqual(AccessoryProduct.objects.get(name="3/4安全帽").category, self.helmet)
        self.assertIsNone(AccessoryProduct.objects.get(name="雨衣").category)
        # 2026-10-15 規則不變：訂單上的這一列仍是自填，不改掛主檔
        line.refresh_from_db()
        self.assertIsNone(line.accessory_product)

    def test_order_create_puts_learned_item_into_category(self):
        case = store.StoreHandlesOrdersTests("test_custom_accessory_is_added_to_master_once")
        case.client = self.client
        store.intake_fixtures.OrderIntakeTests.setUp(case)
        data = case.custom_accessory("eReady原廠安全帽")
        data["accessories-0-accessory_category"] = str(self.helmet.pk)
        response = case.submit("order_create", **data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(AccessoryProduct.objects.get(name="eReady原廠安全帽").category, self.helmet)

    def test_existing_typed_lines_are_left_untouched_by_category_field(self):
        legacy = AccessoryLine.objects.create(order=self.order, name="大牌版", amount=Decimal("600"))
        form = AccessoryLineForm({"accessory_category": "", "accessory_product": "other", "custom_name": "大牌版", "quantity": "1",
                                  "line_type": "purchase", "amount": "600", "labor_fee": "0", "note": "改備註"}, instance=legacy)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        legacy.refresh_from_db()
        self.assertEqual((legacy.accessory_product, legacy.name, legacy.amount), (None, "大牌版", Decimal("600")))

    def test_master_page_filters_edits_category_and_merges(self):
        self.client.force_login(self.user)
        page = self.client.get(reverse("accessory_product_list"), {"category": self.helmet.pk})
        self.assertContains(page, "輕便安全帽")
        self.assertNotContains(page, "五匹手機架")
        self.assertContains(self.client.get(reverse("accessory_product_list"), {"category": "none"}), "風鏡")
        response = self.client.post(reverse("accessory_product_edit", args=[self.loose.pk]), {
            "name": "風鏡", "category": self.helmet.pk, "sale_price": "300", "labor_fee": "0", "cost": "",
            "active": "on", "note": ""})
        self.assertRedirects(response, reverse("accessory_product_list"), fetch_redirect_response=False)
        self.assertEqual(AccessoryProduct.objects.get(pk=self.loose.pk).category, self.helmet)

        dupe = AccessoryProduct.objects.create(name="輕便型安全帽", category=self.helmet, sale_price=Decimal("700"))
        line = AccessoryLine.objects.create(order=self.order, accessory_product=dupe, name="輕便型安全帽", amount=Decimal("700"))
        self.assertContains(self.client.get(reverse("accessory_product_edit", args=[dupe.pk])), "合併到其他配件")
        response = self.client.post(reverse("accessory_product_merge", args=[dupe.pk]), {"target": self.light.pk})
        self.assertRedirects(response, reverse("accessory_product_list"), fetch_redirect_response=False)
        line.refresh_from_db()
        dupe.refresh_from_db()
        self.assertEqual((line.accessory_product, line.name, line.amount), (self.light, "輕便型安全帽", Decimal("700")))
        self.assertFalse(dupe.active)
        self.assertIn("已合併到「輕便安全帽」", dupe.note)

    def test_category_page_creates_and_only_deletes_empty(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("accessory_category_list")).status_code, 200)
        self.client.post(reverse("accessory_category_list"), {"name": "後貨架", "sort_order": "30", "active": "on"})
        self.assertTrue(AccessoryCategory.objects.filter(name="後貨架").exists())
        self.client.post(reverse("accessory_category_list"), {"action": "delete", "category_id": self.helmet.pk})
        self.assertTrue(AccessoryCategory.objects.filter(pk=self.helmet.pk).exists())
        empty = AccessoryCategory.objects.get(name="後貨架")
        self.client.post(reverse("accessory_category_list"), {"action": "delete", "category_id": empty.pk})
        self.assertFalse(AccessoryCategory.objects.filter(pk=empty.pk).exists())
