"""T-179（使用者 2026-11-14 選方案 1）：配件主檔依 bikecity 訂購表重建。

- X：自填加購名稱只在「這次新增或改了名稱的列」加回主檔，舊單再存檔不會把已刪的名稱加回來。
- 一個配件可屬於多個類別（多對多，舊的單一類別外鍵同步寫入排序最前的類別）。
- 類別管理恢復：可新增、改名、排序、停用；只能刪沒有配件的類別。
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from sales.models import AccessoryCategory, AccessoryLine, AccessoryProduct
from sales.tests import test_completed_order_corrections as correction_tests

WORKSPACE = {"HTTP_X_ORDER_WORKSPACE": "1", "HTTP_ACCEPT": "application/json"}
ROW = {"accessory_category": "", "accessory_product": "other", "custom_name": "", "quantity": "1",
       "line_type": "purchase", "amount": "0", "labor_fee": "0", "note": ""}


class OrderSaveLearnsOnlyNewRowsTests(TestCase):
    setUpTestData = classmethod(correction_tests.CompletedOrderCorrectionTests.setUpTestData.__func__)
    setUp = correction_tests.CompletedOrderCorrectionTests.setUp
    order = correction_tests.CompletedOrderCorrectionTests.order
    payload = correction_tests.CompletedOrderCorrectionTests.payload

    def save(self, order, existing=(), new=(), **overrides):
        order.refresh_from_db()
        data = self.payload(order, **overrides)
        rows = [*existing, *new]
        data.update({"accessories-TOTAL_FORMS": str(len(rows)), "accessories-INITIAL_FORMS": str(len(existing))})
        for index, row in enumerate(rows):
            data.update({f"accessories-{index}-{key}": value for key, value in {**ROW, **row}.items()})
        response = self.client.post(reverse("order_edit", args=[order.pk]), data, **WORKSPACE)
        self.assertEqual(response.status_code, 200, response.content[:800])
        self.assertTrue(response.json()["ok"], response.json())
        return response.json()

    def old_row(self, line, **changes):
        return {"id": str(line.pk), "custom_name": line.name, "amount": str(line.amount),
                "labor_fee": str(line.labor_fee), "line_type": line.line_type, **changes}

    def test_resaving_old_order_does_not_bring_deleted_name_back(self):
        order = self.order()
        line = AccessoryLine.objects.create(order=order, name="腳踏飛翼", amount=Decimal("1150"))
        self.save(order, existing=[self.old_row(line)], owner_phone="0911222333")
        self.assertFalse(AccessoryProduct.objects.filter(name="腳踏飛翼").exists())
        line.refresh_from_db()
        self.assertEqual((line.name, line.amount, line.accessory_product_id), ("腳踏飛翼", Decimal("1150"), None))

    def test_new_and_renamed_rows_are_still_learned(self):
        category = AccessoryCategory.objects.get(name="其他")
        order = self.order()
        line = AccessoryLine.objects.create(order=order, name="舊名稱", amount=Decimal("300"))
        payload = self.save(order, existing=[self.old_row(line, custom_name="改過的名稱", accessory_category=str(category.pk))],
                            new=[{"custom_name": "新配件", "accessory_category": str(category.pk), "amount": "500"}])
        self.assertEqual(set(AccessoryProduct.objects.values_list("name", flat=True)), {"改過的名稱", "新配件"})
        self.assertFalse(AccessoryProduct.objects.filter(name="舊名稱").exists())
        self.assertEqual({item["name"] for item in payload["accessory_products_added"]}, {"改過的名稱", "新配件"})


class MultiCategoryAccessoryTests(TestCase):
    setUpTestData = classmethod(correction_tests.CompletedOrderCorrectionTests.setUpTestData.__func__)

    def setUp(self):
        self.client.force_login(self.user)
        self.saluto = AccessoryCategory.objects.create(name="Saluto 精品配件", sort_order=40)
        self.sui = AccessoryCategory.objects.create(name="SUI 精品配件", sort_order=50)
        self.kick = AccessoryProduct.objects.create(name="SUZUKI 踩發桿", sale_price=Decimal("2000"), labor_fee=Decimal("100"))
        self.kick.categories.set([self.sui, self.saluto])
        self.only_sui = AccessoryProduct.objects.create(name="SUI 前風鏡", sale_price=Decimal("3200"))
        self.only_sui.categories.add(self.sui)

    def test_old_foreign_key_follows_first_category(self):
        self.kick.refresh_from_db()
        self.assertEqual(self.kick.category, self.saluto)  # 排序最前
        self.kick.categories.remove(self.saluto)
        self.kick.refresh_from_db()
        self.assertEqual(self.kick.category, self.sui)
        self.sui.category_products.remove(self.kick)  # 從類別那一端移除
        self.kick.refresh_from_db()
        self.assertIsNone(self.kick.category)

    def test_one_product_shows_in_every_category_tab_but_once_in_all(self):
        url = reverse("accessory_product_list")
        response = self.client.get(url)
        counts = {tab["label"]: tab["count"] for tab in response.context["tabs"]}
        self.assertEqual((counts["Saluto 精品配件"], counts["SUI 精品配件"]), (1, 2))
        self.assertEqual(response.context["page_obj"].paginator.count, AccessoryProduct.objects.count())
        self.assertContains(response, "Saluto 精品配件、SUI 精品配件")
        for category in (self.saluto, self.sui):
            names = [row["product"].name for row in self.client.get(url, {"category": category.pk}).context["rows"]]
            self.assertIn("SUZUKI 踩發桿", names)

    def test_order_menu_lists_product_under_each_category(self):
        from sales.forms import AccessoryLineForm
        html = str(AccessoryLineForm()["accessory_product"])
        for label in ("Saluto 精品配件", "SUI 精品配件"):
            group = html.split(f'<optgroup label="{label}">', 1)[1].split("</optgroup>", 1)[0]
            self.assertIn(f'value="{self.kick.pk}"', group)
        self.assertLess(html.index('<optgroup label="Saluto 精品配件">'), html.index('<optgroup label="SUI 精品配件">'))

    def test_edit_form_saves_several_categories_and_bulk_keeps_others(self):
        response = self.client.post(reverse("accessory_product_edit", args=[self.only_sui.pk]), {
            "name": "SUI 前風鏡", "categories": [self.sui.pk, self.saluto.pk], "sale_price": "3200", "labor_fee": "0",
            "cost": "", "active": "on", "note": ""})
        self.assertRedirects(response, reverse("accessory_product_list"), fetch_redirect_response=False)
        self.assertEqual(set(self.only_sui.categories.all()), {self.sui, self.saluto})
        # 批次修改只送這一列，移出 Saluto、保留 SUI。
        self.only_sui.refresh_from_db()
        prefix = f"p{self.only_sui.pk}"
        response = self.client.post(reverse("accessory_product_list"), {
            "row": [str(self.only_sui.pk)], f"{prefix}-name": "SUI 前風鏡", f"{prefix}-categories": [str(self.sui.pk)],
            f"{prefix}-sale_price": "3200", f"{prefix}-labor_fee": "0", f"{prefix}-cost": "", f"{prefix}-active": "on",
            f"{prefix}-version": self.only_sui.updated_at.isoformat()})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(self.only_sui.categories.all()), [self.sui])
        self.assertEqual(set(self.kick.categories.all()), {self.sui, self.saluto})
        from django.contrib.admin.models import LogEntry
        self.assertIn("類別：Saluto 精品配件、SUI 精品配件 → SUI 精品配件",
                      LogEntry.objects.filter(object_id=str(self.only_sui.pk)).latest("pk").change_message)

    def test_category_with_products_cannot_be_deleted(self):
        self.client.post(reverse("accessory_category_list"), {"action": "delete", "category_id": self.saluto.pk})
        self.assertTrue(AccessoryCategory.objects.filter(pk=self.saluto.pk).exists())


class RebuildAccessoryCatalogCommandTests(TestCase):
    setUpTestData = classmethod(correction_tests.CompletedOrderCorrectionTests.setUpTestData.__func__)
    order = correction_tests.CompletedOrderCorrectionTests.order

    def setUp(self):
        from django.contrib.auth import get_user_model
        get_user_model().objects.create_user("admin", password="test-only-123")
        self.helmet = AccessoryCategory.objects.get(name="安全帽")
        self.old = AccessoryProduct.objects.create(name="踩發桿", sale_price=Decimal("2100"))
        self.old.categories.add(self.helmet)
        self.unused = AccessoryProduct.objects.create(name="增高螺絲", sale_price=Decimal("100"), active=False)
        self.sale = self.order()
        self.purchase = AccessoryLine.objects.create(order=self.sale, accessory_product=self.old, name="踩發桿",
                                                     amount=Decimal("2100"), labor_fee=Decimal("0"), note="客人指定")
        self.gift = AccessoryLine.objects.create(order=self.sale, accessory_product=self.old, name="踩發桿",
                                                 line_type="gift", amount=Decimal("0"))
        self.typed = AccessoryLine.objects.create(order=self.sale, name="腳踏飛翼", amount=Decimal("1150"))

    def run_command(self, *args, stdin=""):
        import io
        import sys
        from unittest import mock
        from django.core.management import call_command
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(stdin)):
            call_command("rebuild_accessory_catalog", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_writes_nothing(self):
        output = self.run_command()
        self.assertIn("斷開主檔連結的明細 2 列、1 張訂單", output)
        self.assertIn("建立配件 57 筆（表格 58 列）", output)
        self.assertIn("SUZUKI 踩發桿｜Saluto 精品配件、SUI 精品配件｜售價 2,000｜工資 100", output)
        self.assertEqual(AccessoryProduct.objects.count(), 2)

    def test_apply_keeps_order_history_and_restore_brings_old_catalog_back(self):
        from sales.models import OrderChange
        from sales.services.document_signing import current_fingerprint
        before_print = current_fingerprint(self.sale, "contract")
        backup = self.run_command("--export")
        output = self.run_command("--apply", stdin=backup)
        self.assertIn("已套用", output)
        # 主檔：只剩表格的 57 筆，踩發桿一筆掛兩類；類別只剩 5 個。
        self.assertEqual(AccessoryProduct.objects.count(), 57)
        self.assertEqual(list(AccessoryCategory.objects.order_by("sort_order").values_list("name", flat=True)),
                         ["車身部品配件", "車主周邊配件", "eReady 精品配件", "Saluto 精品配件", "SUI 精品配件"])
        kick = AccessoryProduct.objects.get(name="SUZUKI 踩發桿")
        self.assertEqual(sorted(kick.categories.values_list("name", flat=True)), ["SUI 精品配件", "Saluto 精品配件"])
        self.assertEqual((kick.sale_price, kick.labor_fee, kick.cost), (Decimal("2000"), Decimal("100"), None))
        self.assertEqual(AccessoryProduct.objects.get(name="TAKEWAY 逆磁浮減震手機架 LA3-PH05-AnvR").labor_fee, Decimal("60"))
        self.assertFalse(AccessoryProduct.objects.filter(name__in=["踩發桿", "增高螺絲"]).exists())
        # 舊單：名稱、類型、金額、備註不變，只是不連主檔；簽署指紋不變；寫了 OrderChange。
        for line, expected in ((self.purchase, ("踩發桿", "purchase", Decimal("2100"), "客人指定")),
                               (self.gift, ("踩發桿", "gift", Decimal("0"), ""))):
            line.refresh_from_db()
            self.assertEqual((line.name, line.line_type, line.amount, line.note), expected)
            self.assertIsNone(line.accessory_product_id)
        self.sale.refresh_from_db()
        self.assertEqual(current_fingerprint(self.sale, "contract"), before_print)
        self.assertTrue(OrderChange.objects.filter(order=self.sale, reason__startswith="配件主檔重建（T-179）").exists())
        # 舊單再存檔（X）不會把舊名稱加回主檔。
        from sales.services.accessory_catalog import learn_custom_accessories
        self.assertEqual(learn_custom_accessories(self.sale, "測試", names=set()), [])

        output = self.run_command("--restore", stdin=backup)
        self.assertIn("已回復", output)
        self.assertEqual(set(AccessoryProduct.objects.values_list("pk", "name")), {(self.old.pk, "踩發桿"), (self.unused.pk, "增高螺絲")})
        self.assertEqual(list(AccessoryProduct.objects.get(pk=self.old.pk).categories.all()), [self.helmet])
        self.purchase.refresh_from_db()
        self.gift.refresh_from_db()
        self.assertEqual((self.purchase.accessory_product_id, self.gift.accessory_product_id), (self.old.pk, self.old.pk))
        self.assertEqual(AccessoryCategory.objects.count(), 7)

    def test_apply_refuses_stale_backup(self):
        from django.core.management.base import CommandError
        backup = self.run_command("--export")
        AccessoryProduct.objects.filter(pk=self.unused.pk).update(sale_price=Decimal("150"))
        with self.assertRaisesMessage(CommandError, "備份和目前的配件主檔不一致"):
            self.run_command("--apply", stdin=backup)
        self.assertEqual(AccessoryProduct.objects.count(), 2)

    def test_recycle_bin_orders_get_audit_and_fingerprint_check(self):
        # 2.10.1：回收區（已刪除）的訂單也有連主檔的明細；備份要含它的簽署指紋，套用後也要寫 OrderChange。
        import json
        from django.utils import timezone
        from sales.models import OrderChange, SalesOrder
        deleted = self.order(owner_name="回收區車主")
        AccessoryLine.objects.create(order=deleted, accessory_product=self.old, name="踩發桿", amount=Decimal("2100"))
        SalesOrder.all_objects.filter(pk=deleted.pk).update(deleted_at=timezone.now())
        backup = self.run_command("--export")
        self.assertIn(deleted.pk, {row["id"] for row in json.loads(backup)["orders"]})
        self.assertIn("斷開主檔連結的明細 3 列、2 張訂單", self.run_command())
        self.run_command("--apply", stdin=backup)
        self.assertTrue(OrderChange.objects.filter(order_id=deleted.pk, reason__startswith="配件主檔重建（T-179）").exists())
        self.assertIsNone(AccessoryLine.objects.get(order_id=deleted.pk).accessory_product_id)
        self.run_command("--restore", stdin=backup)
        self.assertEqual(AccessoryLine.objects.get(order_id=deleted.pk).accessory_product_id, self.old.pk)
        self.assertEqual(OrderChange.objects.filter(order_id=deleted.pk, reason__contains="回復").count(), 1)
