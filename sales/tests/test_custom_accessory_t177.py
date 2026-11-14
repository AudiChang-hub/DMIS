"""T-177（使用者 2026-11-14 選 B）：贈送的自填名稱維持不加進配件清單，說明改清楚、贈送列不要求類別；
訂單頁自動儲存把加購的新名稱加進主檔後，同一頁新增的下一列要立刻看得到（不必重新整理）。"""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from sales.forms import AccessoryLineForm
from sales.models import AccessoryCategory, AccessoryProduct
from sales.tests import test_completed_order_corrections as correction_tests

WORKSPACE = {"HTTP_X_ORDER_WORKSPACE": "1", "HTTP_ACCEPT": "application/json"}
ROW = {"accessory_category": "", "accessory_product": "other", "custom_name": "", "quantity": "1",
       "line_type": "purchase", "amount": "0", "labor_fee": "0", "note": ""}


class GiftCustomNameTests(TestCase):
    def test_gift_row_needs_no_category_but_purchase_still_does(self):
        gift = AccessoryLineForm({**ROW, "custom_name": "全聯禮券", "line_type": "gift"}, allow_manual=True)
        self.assertTrue(gift.is_valid(), gift.errors)
        purchase = AccessoryLineForm({**ROW, "custom_name": "雨衣", "amount": "200"}, allow_manual=True)
        self.assertFalse(purchase.is_valid())
        self.assertIn("accessory_category", purchase.errors)


class OrderPageLearnedAccessoryTests(TestCase):
    setUpTestData = classmethod(correction_tests.CompletedOrderCorrectionTests.setUpTestData.__func__)
    setUp = correction_tests.CompletedOrderCorrectionTests.setUp
    order = correction_tests.CompletedOrderCorrectionTests.order
    payload = correction_tests.CompletedOrderCorrectionTests.payload

    def save(self, order, *rows):
        data = self.payload(order)
        data["accessories-TOTAL_FORMS"] = str(len(rows))
        for index, row in enumerate(rows):
            data.update({f"accessories-{index}-{key}": value for key, value in {**ROW, **row}.items()})
        response = self.client.post(reverse("order_edit", args=[order.pk]), data, **WORKSPACE)
        self.assertEqual(response.status_code, 200, response.content[:800])
        payload = response.json()
        self.assertTrue(payload["ok"], payload)
        return payload

    def test_hint_says_only_purchase_names_join_the_list(self):
        page = self.client.get(reverse("order_detail", args=[self.order().pk])).content.decode()
        self.assertIn("加購的自填名稱存檔後會加進該類別", page)
        self.assertIn("贈送不會加進清單", page)
        self.assertNotIn("存檔後會自動加進該類別，下次直接選", page)

    def test_autosave_returns_learned_purchase_name_for_the_next_row(self):
        category = AccessoryCategory.objects.get(name="原廠配件")
        payload = self.save(self.order(), {"custom_name": "後照鏡座", "accessory_category": str(category.pk), "amount": "650"})
        product = AccessoryProduct.objects.get(name="後照鏡座")
        self.assertEqual(payload["accessory_products_added"], [{
            "id": product.pk, "name": "後照鏡座", "category": "原廠配件", "sale_price": "650", "labor_fee": "0",
        }])
        self.assertIn("原廠配件", payload["accessory_category_order"])

    def test_name_already_in_master_returns_nothing(self):
        # 贈送不加進主檔由 test_store_handles_orders 把關；這裡確認沒有新名稱時不帶清單。
        category = AccessoryCategory.objects.get(name="其他")
        AccessoryProduct.objects.create(name="雨衣", category=category, sale_price=200)
        payload = self.save(self.order(), {"custom_name": "雨衣", "accessory_category": str(category.pk), "amount": "200"})
        self.assertNotIn("accessory_products_added", payload)
        self.assertEqual(AccessoryProduct.objects.filter(name="雨衣").count(), 1)

class LearnedAccessoryScriptTests(SimpleTestCase):
    def test_script_adds_learned_names_to_rows_template_and_prices(self):
        script = (Path(settings.BASE_DIR) / "templates/sales/_order_form_scripts.html").read_text(encoding="utf-8")
        handler = script.split("function addLearnedAccessories(", 1)[1].split("\n  }\n", 1)[0]
        for needle in ('byId("empty-accessory")', "accessoryProductData[", "row.accessoryGroups", "filterAccessoryProducts(row)"):
            self.assertIn(needle, handler)
        self.assertIn("accessory_products_added", script)
