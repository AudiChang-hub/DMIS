"""T-281（使用者 2026-11-21「點擊換頁很慢」）：鎖住常用頁面的查詢數，不隨列數增加。

正式站量測（2.35.1）：
- 全部訂單搜尋 50 列 212 個查詢：每列重查品牌別名（VehicleBrand ×153）、交車後未結清標記逐筆查匯入快照（×37）。
- 給付頁：每張車行單逐筆查台數獎金（×12）、營運資料、配件、其他費用（各 ×5）。
- 訂單頁：收款明細 formset 每畫一列重查收款（×13）與訂單。
這裡用合成資料重現：列數變多，查詢數不變。
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from sales.models import (
    LegacyImportBatch, LegacyImportRow, LegacySalesSnapshot, PaymentRecord, SalesOrder, VehicleBrand, VehicleColor, VehicleModel,
)
from sales.reporting import payouts
from sales.tests.test_dealer_payouts_t150 import PayoutTestBase


class OrderSearchQueryCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("t281-admin", password="Test-Only-123")
        parent = VehicleBrand.objects.create(name="T281品牌", aliases="T281B")
        VehicleBrand.objects.create(name="T281子品牌", parent=parent)
        cls.model = VehicleModel.objects.create(brand="T281品牌", name="T281機種", energy_type="gas", displacement_cc=125)
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="白")
        cls.batch = LegacyImportBatch.objects.create(import_type="operations", original_filename="t281.xlsx", file_size=0)
        cls.seq = 0

    def setUp(self):
        self.client.force_login(self.admin)

    def add_orders(self, count):
        for _ in range(count):
            type(self).seq += 1
            order = SalesOrder.objects.create(
                owner_name=f"T281合成車主{self.seq}", owner_phone="0912345678", owner_address="合成地址",
                owner_id_number="A123456789", vehicle_model=self.model, color=self.color)
            # 交車後的單才會算「款項未結清」；一半是 Excel 匯入單（不標記），一半是系統單。
            SalesOrder.all_objects.filter(pk=order.pk).update(status=SalesOrder.Status.COMPLETED)
            if self.seq % 2:
                row = LegacyImportRow.objects.create(batch=self.batch, sheet_name="銷貨", source_row=self.seq,
                                                     fingerprint=f"t281-{self.seq}")
                LegacySalesSnapshot.objects.create(order=order, import_row=row)

    def search(self):
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(reverse("order_list"), {"q": "T281品牌"})
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("T281合成車主1", html)
        return len(captured.captured_queries), html

    def test_search_query_count_does_not_grow_with_rows(self):
        self.add_orders(2)
        few, _html = self.search()
        self.add_orders(6)
        many, html = self.search()
        self.assertEqual(few, many, "全部訂單搜尋的查詢數不可隨列數增加（T-281）")



class DealerPayoutQueryCountTests(PayoutTestBase):
    """給付頁：正式站每張車行單逐筆查台數獎金（×12）、營運資料、配件、其他費用（各 ×5）。"""

    def add_orders(self):
        self.registered(cash_receivable_v2=True)
        self.registered(
            cash_receivable_v2=True, payment_type="installment", installment_amount=Decimal("60000"),
            installment_company="測試分期", installment_periods=24,
            payment_splits=[{"method": "cash", "amount": 19800}, {"method": "installment", "amount": 60000}])
        self.registered()

    def count(self):
        with CaptureQueriesContext(connection) as captured:
            items = payouts.collect_items()
        return len(captured.captured_queries), items

    def page_count(self):
        self.client.force_login(self.admin)
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(reverse("dealer_payout_list"))
        self.assertEqual(response.status_code, 200)
        return len(captured.captured_queries)

    def test_collect_items_query_count_does_not_grow_with_orders(self):
        self.add_orders()
        few, items = self.count()
        page_few = self.page_count()
        self.add_orders()
        self.add_orders()
        many, more_items = self.count()
        page_many = self.page_count()
        self.assertGreater(len(more_items), len(items))
        self.assertEqual(few, many, "給付頁應付計算的查詢數不可隨車行單數增加（T-281）")
        self.assertEqual(page_few, page_many, "給付頁的查詢數不可隨車行單數增加（T-281）")


class OrderDetailQueryCountTests(PayoutTestBase):
    """訂單頁：收款明細 formset 的 get_queryset 每次都重新 filter，模板每畫一列就重查一次（正式站 ×13）。"""

    def detail_count(self, order):
        self.client.force_login(self.admin)
        self.client.get(reverse("order_detail", args=[order.pk]))  # 先暖身：排除登入 session、設定快取等一次性查詢
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(reverse("order_detail", args=[order.pk]))
        self.assertEqual(response.status_code, 200)
        return len(captured.captured_queries), response.content.decode()

    def test_order_page_query_count_does_not_grow_with_payment_rows(self):
        order = self.make_order()
        PaymentRecord.objects.create(order=order, item_name="T281收款1", expected_amount=0, received_amount=100)
        few, _html = self.detail_count(order)
        for index in range(2, 7):
            PaymentRecord.objects.create(order=order, item_name=f"T281收款{index}", expected_amount=0, received_amount=100)
        many, html = self.detail_count(order)
        self.assertIn("T281收款6", html)
        self.assertEqual(few, many, "訂單頁的查詢數不可隨收款列數增加（T-281）")
