"""T-156（使用者 2026-11-13 簡報）：
第 7 頁「應收已經是0，不需要在填實收金額」：應收 0 時不填實收也能完成交車，且不記一筆 0 元收款；應收大於 0 照舊要足額。"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from sales.models import PaymentRecord, SalesOrder
from sales.services.payment_summary import payment_summary
from sales.tests import test_order_lifecycle as lifecycle
from sales.tests import test_order_steps as steps


class ZeroDueDeliveryTests(TestCase):
    setUp = steps.OrderStepTests.setUp
    make_order = steps.OrderStepTests.make_order
    registered_v2 = steps.OrderStepTests.registered_v2
    delivery_payload = lifecycle.OrderLifecycleTests.delivery_payload

    def settled_order(self):
        """頁面開著時（應收大於 0、尾款欄位已顯示）另一筆收款存檔，應收變 0。"""
        order, _vehicle = self.registered_v2()
        total = payment_summary(order)["customer_expected"]
        PaymentRecord.objects.create(order=order, item_name="其他已收款", expected_amount=0, received_amount=total,
                                     received_on=date(2026, 11, 12), payment_method="匯款", confirmed=True)
        order = SalesOrder.objects.get(pk=order.pk)
        self.assertEqual(payment_summary(order)["delivery_due"], Decimal("0"))
        return order

    def post(self, order, **balance):
        self.client.force_login(self.user)
        payload = {**self.delivery_payload(), **{f"balance-{key}": value for key, value in balance.items()}}
        return self.client.post(reverse("delivery_complete", args=[order.pk]), payload, follow=True)

    def assert_delivered_without_zero_receipt(self, order):
        order.refresh_from_db()
        self.assertTrue(order.is_delivered)
        balance = PaymentRecord.objects.get(order=order, system_key="balance")
        self.assertFalse(balance.confirmed)
        self.assertFalse(balance.received_amount)

    def test_zero_due_completes_without_received_amount(self):
        order = self.settled_order()
        response = self.post(order, received_amount="", received_on="", payment_method="現金")
        self.assertNotContains(response, "請填寫實收金額")
        self.assert_delivered_without_zero_receipt(order)

    def test_zero_due_with_zero_typed_does_not_record_zero_receipt(self):
        order = self.settled_order()
        self.post(order, received_amount="0", received_on="", payment_method="現金")
        self.assert_delivered_without_zero_receipt(order)

    def test_positive_due_still_requires_full_amount(self):
        order, _vehicle = self.registered_v2()
        due = payment_summary(order)["delivery_due"]
        self.assertGreater(due, 0)
        self.assertContains(self.post(order, received_amount=""), "請填寫實收金額")
        self.assertContains(self.post(order, received_amount="0", received_on="2026-11-13", payment_method="現金"), "不得少於應收")
        order.refresh_from_db()
        self.assertFalse(order.is_delivered)
        self.post(order, received_amount=str(due), received_on="2026-11-13", payment_method="現金")
        order.refresh_from_db()
        self.assertTrue(order.is_delivered)
        self.assertTrue(PaymentRecord.objects.get(order=order, system_key="balance").confirmed)

    def test_balance_sheet_has_zero_due_hint(self):
        order, _vehicle = self.registered_v2()
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        self.assertIn("data-balance-hint-zero hidden>目前沒有應收尾款，實收金額不必填", page)
