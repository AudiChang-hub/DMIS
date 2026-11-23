"""T-289 訂單總覽區塊位置固定：每張單同一組區塊、同一欄、同一順序，資料少也照樣輸出。"""
import re
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from sales.models import AccessoryLine, PaymentRecord, SalesOrder
from sales.services.order_overview import OVERVIEW_COLUMNS, build_order_overview
from sales.tests import test_order_lifecycle as lifecycle

CORE_SECTIONS = ["order", "owner", "vehicle", "registration", "price", "installment", "delivery", "note"]
LEFT = ["order", "owner", "vehicle", "delivery", "note"]
RIGHT = ["registration", "price", "installment"]


class OrderOverviewLayoutTests(TestCase):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def sparse_order(self):
        """現金、沒有加購、沒有收支、沒有備註。"""
        order, _vehicle = self.make_order(deposit=Decimal("0"))
        order.payment_records.all().delete()
        order.accessories.all().delete()
        return SalesOrder.objects.get(pk=order.pk)

    def rich_order(self):
        """分期、有加購、汰舊、長備註、有收支。"""
        order, _vehicle = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(
            payment_type=SalesOrder.PaymentType.INSTALLMENT, installment_company="示範分期", installment_periods=24,
            installment_amount=Decimal("60000"), installment_monthly=Decimal("2800"),
            is_trade_in_subsidy=True, trade_in_plate="ABC-123", note="長備註" * 80,
        )
        AccessoryLine.objects.create(order=order, name="後架", quantity=1, amount=Decimal("1200"))
        PaymentRecord.objects.create(order=order, item_name="訂金", expected_amount=Decimal("5000"), received_amount=Decimal("5000"))
        return SalesOrder.objects.get(pk=order.pk)

    def keys(self, overview):
        return [section["key"] for section in overview["sections"]]

    def test_sparse_order_still_lists_every_core_section_and_table(self):
        overview = build_order_overview(self.sparse_order())
        self.assertEqual(self.keys(overview), CORE_SECTIONS)
        self.assertEqual([table["key"] for table in overview["tables"]], ["accessories", "payments"])
        installment = next(section for section in overview["sections"] if section["key"] == "installment")
        self.assertTrue(all(row["value"] == "—" and row["copy"] == "" for row in installment["rows"]))
        # 「複製全部」照舊只帶有資料的欄位：空的分期、空明細表不出現。
        self.assertNotIn("【分期】", overview["plain_text"])
        self.assertNotIn("【加購項目與贈品】", overview["plain_text"])
        self.assertNotIn("【收入與支出】", overview["plain_text"])

    def test_columns_are_fixed_regardless_of_content(self):
        sparse = build_order_overview(self.sparse_order())
        rich = build_order_overview(self.rich_order())
        for overview in (sparse, rich):
            left, right = ([section["key"] for section in column] for column in overview["columns"])
            self.assertEqual([key for key in left if key in CORE_SECTIONS], LEFT)
            self.assertEqual([key for key in right if key in CORE_SECTIONS], RIGHT)
            # 欄內上下順序＝跳轉順序；手機單欄依 position 排，也是跳轉順序。
            for column in overview["columns"]:
                positions = [section["position"] for section in column]
                self.assertEqual(positions, sorted(positions))
            self.assertEqual([section["position"] for section in overview["sections"]], list(range(1, len(overview["sections"]) + 1)))
        self.assertEqual([key for key in self.keys(rich) if key in CORE_SECTIONS], CORE_SECTIONS)
        self.assertIn("trade_in", [section["key"] for section in rich["columns"][0]])
        for keys in OVERVIEW_COLUMNS:
            self.assertEqual(len(keys), len(set(keys)))
        self.assertFalse(set(OVERVIEW_COLUMNS[0]) & set(OVERVIEW_COLUMNS[1]))

    def test_rows_inside_each_core_section_are_fixed(self):
        sparse = build_order_overview(self.sparse_order())
        rich = build_order_overview(self.rich_order())
        labels = lambda overview, key: [row["label"] for row in next(s for s in overview["sections"] if s["key"] == key)["rows"]]
        for key in CORE_SECTIONS:
            self.assertEqual(labels(sparse, key), labels(rich, key), key)
        price = {row["label"]: row for row in next(s for s in sparse["sections"] if s["key"] == "price")["rows"]}
        self.assertEqual((price["牌險"]["value"], price["牌險"]["copy"]), ("—", ""))
        self.assertEqual(price["分期外應收"]["value"], "—")

    def test_page_renders_two_fixed_columns_and_jump_in_section_order(self):
        self.client.force_login(self.user)
        for order in (self.sparse_order(), self.rich_order()):
            page = self.client.get(reverse("order_overview", args=[order.pk]) + "?fragment=1").content.decode()
            grid = page.split('class="order-overview__grid"', 1)[1].split('class="order-overview__tables"', 1)[0]
            chunks = grid.split('data-overview-column="')[1:]
            self.assertEqual([chunk[0] for chunk in chunks], ["1", "2"])
            ids = [re.findall(r'<section class="order-overview__card" id="overview-(\w+)"', chunk) for chunk in chunks]
            self.assertEqual([key for key in ids[0] if key in CORE_SECTIONS], LEFT)
            self.assertEqual([key for key in ids[1] if key in CORE_SECTIONS], RIGHT)
            jumps = re.findall(r'<a href="#overview-(\w+)" data-overview-jump>', page)
            self.assertEqual([key for key in jumps if key in CORE_SECTIONS + ["accessories", "payments"]],
                             CORE_SECTIONS + ["accessories", "payments"])
            orders = dict(re.findall(r'id="overview-(\w+)" style="--overview-order: (\d+)"', page))
            self.assertEqual([key for key in jumps if key in orders], sorted(orders, key=lambda key: int(orders[key])))
        self.assertIn("沒有加購項目或贈品", self.client.get(reverse("order_overview", args=[self.sparse_order().pk])).content.decode())

    def test_css_uses_fixed_columns_not_masonry(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "order-overview.css").read_text(encoding="utf-8")
        self.assertNotRegex(css, r"\.order-overview__grid \{[^}]*columns:")
        self.assertIn(".order-overview__columns .order-overview__card { order: var(--overview-order, 0); }", css)
        self.assertIn("@container order-overview-grid (min-width: 700px)", css)
