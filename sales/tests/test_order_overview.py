"""訂單總覽：唯讀列出整張訂單、側邊列入口、片段載入、權限與複製用純文字。"""
import json
import re
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from sales.access.registry import ROUTES
from sales.models import AccessoryLine, OtherFeeLine
from sales.services.order_intake import ORDER_PK_ROUTES
from sales.services.order_overview import build_order_overview
from sales.tests import test_order_lifecycle as lifecycle


class OrderOverviewTests(TestCase):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def overview_order(self):
        order, vehicle = self.make_order(deposit=Decimal("5000"))
        from sales.services.print_company import ensure_order_company
        ensure_order_company(order)
        order.owner_birth_date = date(1992, 1, 21)
        order.owner_email = "owner@example.test"
        order.note = "週六下午交車"
        order.save(update_fields=["owner_birth_date", "owner_email", "note", "updated_at"])
        AccessoryLine.objects.create(order=order, name="後架", quantity=2, amount=Decimal("1200"), labor_fee=Decimal("300"))
        OtherFeeLine.objects.create(order=order, name="代辦費", amount=Decimal("1500"))
        return order, vehicle

    def test_route_is_scoped_like_order_detail(self):
        self.assertEqual(ROUTES["order_overview"], ("orders", "auto"))
        self.assertIn("order_overview", ORDER_PK_ROUTES)

    def test_full_page_lists_order_data_read_only(self):
        order, vehicle = self.overview_order()
        self.client.force_login(self.user)
        response = self.client.get(reverse("order_overview", args=[order.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store, max-age=0")
        page = response.content.decode()
        for text in (order.number, "王小明", "A123456789", "0912345678", "新北市汐止區", "SUI 125", "UQ125DA",
                     vehicle.engine_number, "1992/01/21", "民國 81 年 1 月 21 日", "後架", "代辦費", "週六下午交車",
                     order.print_company_snapshot["legal_name"]):
            self.assertIn(text, page)
        # 唯讀：沒有任何表單或輸入欄位（搜尋框除外）。
        self.assertNotIn("<form", page.split('data-order-overview', 1)[1])
        self.assertEqual(re.findall(r"<input(?![^>]*data-overview-search)", page.split('data-order-overview', 1)[1]), [])
        self.assertIn('data-overview-copy-all', page)

    def test_fragment_has_no_page_shell_and_copies_raw_numbers(self):
        order, _vehicle = self.overview_order()
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_overview", args=[order.pk]) + "?fragment=1").content.decode()
        self.assertNotIn("<html", page)
        self.assertNotIn("<h1", page)
        # 金額畫面顯示千分位，複製值是純數字。
        self.assertIn('data-label="車價" data-copy="75000"', page)
        self.assertIn("$75,000", page)
        plain = json.loads(re.search(r'<script id="order-overview-text" type="application/json">(.*?)</script>', page, re.S).group(1))
        self.assertIn("【車主】", plain)
        self.assertIn("證件號碼／統一編號：A123456789", plain)
        self.assertIn("後架\t加購\t2", plain)
        # 空白欄位不出現在複製全部的內容。
        self.assertNotIn("英文姓名", plain)

    def test_order_page_sidebar_links_to_overview(self):
        order, _vehicle = self.make_order()
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        url = reverse("order_overview", args=[order.pk])
        nav = page.split('data-order-nav-panel', 1)[1].split("</aside>", 1)[0]
        self.assertIn(f'data-order-overview-open="{url}"', nav)
        self.assertIn("訂單總覽", nav)
        self.assertIn("data-order-overview-dialog", page)
        self.assertIn("js/order-overview.js", page)
        self.assertIn("css/order-overview.css", page)

    def test_order_section_lists_one_order_date(self):
        order, _vehicle = self.overview_order()
        # 匯入單的 established_on 是領牌日，總覽只列訂單日期（order_date）。
        type(order).objects.filter(pk=order.pk).update(established_on=date(2026, 3, 9), order_date=date(2026, 3, 2))
        order.refresh_from_db()
        overview = build_order_overview(order)
        rows = {row["label"]: row["value"] for row in overview["sections"][0]["rows"]}
        self.assertEqual(rows["訂單日期"], "2026/03/02")
        self.assertNotIn("訂單成立日期", rows)
        self.assertNotIn("訂單成立日期", overview["plain_text"])

    def test_finance_rows_can_be_left_out(self):
        order, _vehicle = self.overview_order()
        order.payment_records.all().delete()
        from sales.models import PaymentRecord
        PaymentRecord.objects.create(order=order, item_name="訂金", expected_amount=Decimal("5000"), received_amount=Decimal("5000"))
        keys = lambda overview: [table["key"] for table in overview["tables"]]
        self.assertIn("payments", keys(build_order_overview(order)))
        self.assertNotIn("payments", keys(build_order_overview(order, include_finance=False)))
