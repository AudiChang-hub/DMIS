"""T-211（2.20.2）：全部訂單列表姓名旁、現金／分期標籤右邊加「汰舊」外框標籤（使用者選樣式 B）。"""
import re

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from sales.models import SalesOrder, VehicleColor, VehicleModel

CHIP = '<span class="trade-in-chip" title="有汰舊換新">汰舊</span>'


class OrderListTradeInChipTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser("t211-admin", password="test-only")
        cls.model = VehicleModel.objects.create(brand="測試", name="汰舊機種", energy_type="gas")
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="白")

    def make(self, name, *, trade_in=False, payment="cash"):
        return SalesOrder.objects.create(
            owner_name=name, owner_phone="0912345678", owner_address="合成測試地址", owner_id_number="A123456789",
            vehicle_model=self.model, color=self.color, payment_type=payment, is_trade_in_subsidy=trade_in,
            installment_company="裕融" if payment == "installment" else "",
        )

    def page(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("order_list"), {"tab": "all", "per_page": 50})
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def line_for(self, page, name):
        lines = [line for line in re.findall(r'<span class="order-owner-line">(.*?)</span>\s*(?:<span class="order-number-stack">|</div>|<span class="order-meta|<small|$)', page, re.S)
                 if f">{name}<" in line]
        self.assertEqual(len(lines), 2, f"{name}：表格與手機卡片各一列")
        return lines

    def test_only_trade_in_orders_show_the_chip_after_payment_chip(self):
        self.make("現金汰舊甲", trade_in=True)
        self.make("分期汰舊乙", trade_in=True, payment="installment")
        self.make("現金一般丙")
        self.make("分期一般丁", payment="installment")
        page = self.page()
        self.assertEqual(page.count(CHIP), 4, "兩張有汰舊 × 表格與手機卡片")
        for name, payment in (("現金汰舊甲", "cash"), ("分期汰舊乙", "installment")):
            for line in self.line_for(page, name):
                self.assertIn(CHIP, line)
                self.assertLess(line.index(f"payment-chip--{payment}"), line.index(CHIP), "汰舊在付款方式標籤右邊")
        for name in ("現金一般丙", "分期一般丁"):
            for line in self.line_for(page, name):
                self.assertNotIn("trade-in-chip", line)

    def test_chip_adds_no_queries_per_order(self):
        self.make("查詢一", trade_in=True)
        self.client.force_login(self.user)
        url = reverse("order_list")
        with CaptureQueriesContext(connection) as few:
            self.client.get(url, {"tab": "all", "per_page": 50})
        for index in range(6):
            self.make(f"查詢多{index}", trade_in=index % 2 == 0, payment="installment" if index % 3 else "cash")
        with CaptureQueriesContext(connection) as many:
            response = self.client.get(url, {"tab": "all", "per_page": 50})
        self.assertEqual(response.content.decode().count(CHIP), 8)
        self.assertEqual(len(few), len(many), "多 6 張訂單不能多查詢（汰舊是訂單欄位）")

    def test_customer_page_rows_do_not_get_the_chip(self):
        # 這次只加在全部訂單列表；共用的訂單列（_order_row）在其他頁面不顯示。
        from django.template.loader import render_to_string

        order = self.make("客戶頁汰舊", trade_in=True)
        html = render_to_string("sales/_order_row.html", {"order": order})
        self.assertNotIn("trade-in-chip", html)
        self.assertIn("trade-in-chip", render_to_string("sales/_order_row.html", {"order": order, "show_trade_in": True}))
