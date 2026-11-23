"""T-288（使用者 2026-11-23）：車行額度功能整個拿掉。

使用者：「車行額度功能整個拿掉，車行資料的額度欄位、超額度提醒、只列超額車行的清單都不要了」。
- 交車不再因車行未付累計被擋，交車時照記未付金額（`DeliveryRecord.on_account_amount`）。
- 「需要處理」沒有車行未付超額度；清單頁不帶參數與舊連結 `?scope=all` 內容相同（見 test_money_card_t278）。
- 車行資料表單沒有額度欄位，送出照常存檔。
- 用語「車行掛帳」改「車行未付」：交車區框標題、交付紀錄、收支區還差，金額不變。
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from sales.forms import SalesSourceForm
from sales.models import DeliveryRecord, OrderEvent, SalesSource
from sales.services.dealer_credit import dealer_outstanding
from sales.tests import test_order_lifecycle as lifecycle
from sales.tests.test_business_gates import BusinessGateTests
from sales.tests.test_channel_finance import ChannelFinanceTests


class DealerDeliveryWithoutLimitTests(TestCase):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order
    delivery_payload = lifecycle.OrderLifecycleTests.delivery_payload
    registered = BusinessGateTests.registered
    v2 = BusinessGateTests.v2

    def dealer_order(self):
        order, _vehicle = self.make_order(dealer=True, deposit=Decimal("0"))
        return self.registered(self.v2(order))

    def test_unpaid_accumulation_never_blocks_delivery_and_records_on_account(self):
        self.client.force_login(self.user)
        for count in (1, 2, 3):
            order = self.dealer_order()
            self.assertEqual(order.delivery_blockers(), [])
            response = self.client.post(reverse("delivery_complete", args=[order.pk]), self.delivery_payload())
            self.assertEqual(response.status_code, 302)
            order.refresh_from_db()
            self.assertTrue(order.is_delivered)
            record = DeliveryRecord.objects.get(order=order)
            self.assertEqual(record.on_account_amount, Decimal("75000"))
            self.assertEqual(dealer_outstanding(self.source.pk), Decimal("75000") * count)
            event = OrderEvent.objects.filter(order=order, event_type="delivery_completed").get()
            self.assertIn("車行未付 75,000 元", event.description)
            self.assertNotIn("掛帳", event.description)

    def test_delivery_box_says_unpaid_without_limit(self):
        delivered = self.dealer_order()
        delivered.complete_delivery(delivered.registration_completed_at, "測試")
        order = self.dealer_order()
        self.client.force_login(self.user)
        html = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        start = html.index('id="dealer-credit"')
        box = html[start:html.index("</p>", start)]
        self.assertIn("<strong>車行未付</strong>", box)
        self.assertIn("本單尚未收清 $75,000", box)
        self.assertIn("其他已交車未收清 $75,000", box)
        self.assertNotIn("額度", box)
        self.assertNotIn("掛帳", box)


class DealerSourceFormWithoutLimitTests(TestCase):
    setUp = ChannelFinanceTests.setUp

    def test_form_has_no_credit_limit_field(self):
        self.assertNotIn("credit_limit", SalesSourceForm(instance=self.dealer).fields)
        self.assertNotIn("credit_limit", {field.name for field in SalesSource._meta.get_fields()})
        self.client.force_login(self.user)
        response = self.client.get(reverse("sales_source_edit", args=[self.dealer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "額度")
        self.assertNotContains(response, 'name="credit_limit"')

    def test_form_submit_still_saves(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("sales_source_edit", args=[self.dealer.pk]), {
            "name": self.dealer.name, "responsible_person": "示範負責人", "phone": "02-23456789",
            "mobile": "0912345678", "address": "新北市汐止區測試路 1 號", "note": "T-288 存檔", "active": "on",
            "sym_vehicle_capacity": "4", "suzuki_vehicle_capacity": "", "credit_limit": "5000",  # 舊欄位送來也忽略
            "line_group_presence": "no",
            "contacts-TOTAL_FORMS": "0", "contacts-INITIAL_FORMS": "0",
            "contacts-MIN_NUM_FORMS": "0", "contacts-MAX_NUM_FORMS": "1000",
            "policies-TOTAL_FORMS": "0", "policies-INITIAL_FORMS": "0",
            "policies-MIN_NUM_FORMS": "0", "policies-MAX_NUM_FORMS": "1000",
        })
        self.assertEqual(response.status_code, 302)
        self.dealer.refresh_from_db()
        self.assertEqual((self.dealer.note, self.dealer.sym_vehicle_capacity), ("T-288 存檔", 4))
        self.assertEqual(self.dealer.source_type, SalesSource.SourceType.DEALER)
