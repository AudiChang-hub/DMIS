"""使用者 2026-11-14 T-178：配件與工資清單依類別分頁籤、可刪除沒用過的配件、清單上直接批次修改。"""
from decimal import Decimal

from django.contrib.admin.models import CHANGE, DELETION, LogEntry
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import AccessoryCategory, AccessoryLine, AccessoryProduct
from sales.tests import test_order_lifecycle as lifecycle


class AccessoryListT178Tests(TestCase):
    setUp_base = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def setUp(self):
        self.setUp_base()
        self.client.force_login(self.user)
        self.helmet = AccessoryCategory.objects.get(name="安全帽")
        self.holder = AccessoryCategory.objects.get(name="手機架")
        # T-179 起類別存在多對多 categories（舊的 category 外鍵由訊號同步）。
        self.light = self.product("輕便安全帽", self.helmet, sale_price=Decimal("800"))
        self.full = self.product("全罩安全帽", self.helmet, sale_price=Decimal("2400"), active=False)
        self.five = self.product("五匹手機架", self.holder, sale_price=Decimal("1200"), labor_fee=Decimal("200"))
        self.loose = AccessoryProduct.objects.create(name="風鏡", sale_price=Decimal("300"), cost=Decimal("120"))
        self.url = reverse("accessory_product_list")

    @staticmethod
    def product(name, *categories, **fields):
        product = AccessoryProduct.objects.create(name=name, **fields)
        product.categories.set(categories)
        product.refresh_from_db()
        return product

    # ---- 頁籤 ----
    def tab_counts(self, response):
        return {tab["label"]: tab["count"] for tab in response.context["tabs"]}

    def test_tabs_list_all_and_each_category_with_counts(self):
        response = self.client.get(self.url)
        counts = self.tab_counts(response)
        self.assertEqual(counts["全部"], 4)
        self.assertEqual(counts["安全帽"], 2)
        self.assertEqual(counts["手機架"], 1)
        self.assertEqual(counts["未分類"], 1)
        self.assertEqual(counts["其他"], 0)  # 啟用中的類別即使沒有配件也列出
        self.assertContains(response, 'class="inventory-scope-tabs accessory-tabs"')

    def test_tab_filters_list_and_keeps_search_and_status(self):
        response = self.client.get(self.url, {"category": self.helmet.pk, "active": "yes"})
        names = [row["product"].name for row in response.context["rows"]]
        self.assertEqual(names, ["輕便安全帽"])
        counts = self.tab_counts(response)
        self.assertEqual((counts["全部"], counts["安全帽"]), (3, 1))  # 筆數套用狀態篩選
        holder_tab = next(tab for tab in response.context["tabs"] if tab["label"] == "手機架")
        self.assertIn("active=yes", holder_tab["url"])
        self.assertIn(f"category={self.holder.pk}", holder_tab["url"])
        # 搜尋在頁籤內作用
        response = self.client.get(self.url, {"category": self.helmet.pk, "q": "全罩"})
        self.assertEqual([row["product"].name for row in response.context["rows"]], ["全罩安全帽"])
        self.assertEqual(self.tab_counts(response)["全部"], 1)

    def test_uncategorised_tab_and_legacy_category_links_still_work(self):
        response = self.client.get(self.url, {"category": "none"})
        self.assertEqual([row["product"].name for row in response.context["rows"]], ["風鏡"])
        self.assertTrue(next(tab for tab in response.context["tabs"] if tab["label"] == "未分類")["active"])

    # ---- 刪除 ----
    def test_unused_accessory_can_be_deleted_with_audit_log(self):
        page = self.client.get(self.url)
        self.assertContains(page, reverse("accessory_product_delete", args=[self.loose.pk]))
        self.assertContains(page, "存檔時會再自動加回清單")
        response = self.client.post(reverse("accessory_product_delete", args=[self.loose.pk]), {"return_query": "category=none"})
        self.assertRedirects(response, f"{self.url}?category=none", fetch_redirect_response=False)
        self.assertFalse(AccessoryProduct.objects.filter(pk=self.loose.pk).exists())
        log = LogEntry.objects.get(object_id=str(self.loose.pk), action_flag=DELETION)
        self.assertEqual((log.user, log.object_repr), (self.user, "風鏡"))

    def test_used_accessory_cannot_be_deleted(self):
        order, _vehicle = self.make_order()
        AccessoryLine.objects.create(order=order, accessory_product=self.five, name=self.five.name, amount=Decimal("1200"))
        page = self.client.get(self.url)
        self.assertNotContains(page, reverse("accessory_product_delete", args=[self.five.pk]))
        self.assertContains(page, "已有 1 筆訂單用過，不能刪除")
        response = self.client.post(reverse("accessory_product_delete", args=[self.five.pk]))
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertTrue(AccessoryProduct.objects.filter(pk=self.five.pk).exists())
        self.assertFalse(LogEntry.objects.filter(action_flag=DELETION).exists())

    # ---- 批次修改 ----
    def row_data(self, product, **changes):
        data = {
            "name": product.name, "categories": [str(pk) for pk in product.categories.values_list("pk", flat=True)],
            "sale_price": str(product.sale_price),
            "labor_fee": str(product.labor_fee), "cost": "" if product.cost is None else str(product.cost),
            "active": "on" if product.active else "", "version": product.updated_at.isoformat(),
        }
        data.update(changes)
        payload = {f"p{product.pk}-{key}": value for key, value in data.items() if not (key == "active" and value == "")}
        payload["row"] = str(product.pk)
        return payload

    def post_rows(self, *rows, return_query=""):
        payload = {"return_query": return_query}
        row_ids = []
        for row in rows:
            row_ids.append(row.pop("row"))
            payload.update(row)
        payload["row"] = row_ids
        return self.client.post(self.url, payload)

    def test_edit_mode_renders_inline_inputs_and_snapshot_notice(self):
        page = self.client.get(self.url, {"edit": "1"})
        self.assertContains(page, f'name="p{self.light.pk}-sale_price" value="800"')
        self.assertContains(page, f'name="p{self.loose.pk}-cost" value="120"')
        self.assertContains(page, "售價與工資是訂單當時的快照")
        self.assertContains(page, "accessory-bulk-edit.js")
        self.assertContains(page, "結束批次修改")

    def test_bulk_update_saves_several_rows_at_once_and_logs(self):
        order, _vehicle = self.make_order()
        line = AccessoryLine.objects.create(order=order, accessory_product=self.five, name=self.five.name,
                                            amount=Decimal("1200"), labor_fee=Decimal("200"))
        response = self.post_rows(
            self.row_data(self.five, sale_price="1500", labor_fee="300"),
            self.row_data(self.loose, categories=[str(self.helmet.pk)], name="防風鏡"),
            self.row_data(self.full, active="on"),
            return_query=f"category={self.helmet.pk}&active=yes",
        )
        self.assertRedirects(response, f"{self.url}?active=yes&category={self.helmet.pk}", fetch_redirect_response=False)
        self.five.refresh_from_db()
        self.loose.refresh_from_db()
        self.full.refresh_from_db()
        self.assertEqual((self.five.sale_price, self.five.labor_fee), (Decimal("1500"), Decimal("300")))
        self.assertEqual((self.loose.name, list(self.loose.categories.all()), self.loose.cost), ("防風鏡", [self.helmet], Decimal("120")))
        self.assertEqual(self.loose.category, self.helmet)  # 舊外鍵同步（T-179）
        self.assertTrue(self.full.active)
        # 舊訂單的配件售價與工資是快照，不跟著改。
        line.refresh_from_db()
        self.assertEqual((line.amount, line.labor_fee), (Decimal("1200"), Decimal("200")))
        log = LogEntry.objects.get(object_id=str(self.five.pk), action_flag=CHANGE)
        self.assertIn("配件售價：1200 → 1500", log.change_message)
        self.assertEqual(LogEntry.objects.filter(action_flag=CHANGE).count(), 3)

    def test_unchanged_rows_are_skipped(self):
        before = self.light.updated_at
        response = self.post_rows(self.row_data(self.light))
        self.assertEqual(response.status_code, 302)
        self.light.refresh_from_db()
        self.assertEqual(self.light.updated_at, before)
        self.assertFalse(LogEntry.objects.exists())

    def test_invalid_row_blocks_the_whole_batch(self):
        response = self.post_rows(
            self.row_data(self.five, sale_price="1500"),
            self.row_data(self.loose, name="輕便安全帽"),  # 和既有配件同名
            self.row_data(self.light, labor_fee="abc"),
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "有 2 項沒通過檢查", status_code=400)
        self.assertContains(response, f'name="p{self.loose.pk}-name" value="輕便安全帽"', status_code=400)
        self.five.refresh_from_db()
        self.assertEqual(self.five.sale_price, Decimal("1200"))
        self.assertFalse(LogEntry.objects.exists())

    def test_two_rows_renamed_to_same_name_are_rejected(self):
        response = self.post_rows(self.row_data(self.five, name="新名稱"), self.row_data(self.loose, name="新名稱"))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AccessoryProduct.objects.filter(name="新名稱").exists())

    def test_stale_row_is_rejected(self):
        payload = self.row_data(self.five, sale_price="999")
        AccessoryProduct.objects.filter(pk=self.five.pk).update(sale_price=Decimal("1300"), updated_at=self.five.updated_at.replace(year=2030))
        response = self.post_rows(payload)
        self.assertContains(response, "剛被其他人修改過", status_code=400)
        self.five.refresh_from_db()
        self.assertEqual(self.five.sale_price, Decimal("1300"))

    # ---- 權限：沿用「配件與工資」畫面權限，僅查看者不能改、不能刪 ----
    def test_view_only_user_cannot_bulk_update_or_delete(self):
        viewer = get_user_model().objects.create_user(username="viewer", password="test-pass-123")
        ScreenAccessGrant.objects.create(user=viewer, screen_key="accessories", view=True)
        UserAccessState.objects.update_or_create(user=viewer, defaults={"configured": True})
        self.client.force_login(viewer)
        page = self.client.get(self.url, {"edit": "1"})
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "accessory-bulk-edit.js")
        self.assertNotContains(page, reverse("accessory_product_delete", args=[self.loose.pk]))
        self.assertEqual(self.post_rows(self.row_data(self.five, sale_price="1")).status_code, 403)
        self.assertEqual(self.client.post(reverse("accessory_product_delete", args=[self.loose.pk])).status_code, 403)
        self.assertTrue(AccessoryProduct.objects.filter(pk=self.loose.pk).exists())
