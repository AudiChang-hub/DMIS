"""使用者 2026-11-03 簡報 p3：收款區的「確認收款」改成收款狀態，寫出還差什麼、去哪裡處理。"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from sales.models import PaymentRecord, SalesOrder
from sales.services.operations_sync import sync_order_operations
from sales.services.order_workspace import receipt_status
from sales.services.payment_summary import payment_summary
from sales.tests import test_order_flow as flow


class ReceiptStatusTests(TestCase):
    setUp = flow.OrderFlowTests.setUp
    make_order = flow.OrderFlowTests.make_order

    def dealer_order(self):
        order = self.make_order()
        order.source = self.dealer
        order.source_type = SalesOrder.SourceType.DEALER
        order.save(update_fields=["source", "source_type", "updated_at"])
        sync_order_operations(order.pk, update_receivables=True)
        return order

    def test_dealer_order_lists_what_is_missing_instead_of_disabled_checkbox(self):
        order = self.dealer_order()
        status = receipt_status(order, payment_summary(order))
        self.assertFalse(status["settled"])
        texts = " ".join(item["text"] for item in status["items"])
        self.assertIn("車行掛帳還差", texts)
        self.assertTrue(any(item["href"] == "#add-payment" for item in status["items"]))

        self.client.force_login(get_root())
        page = self.client.get(reverse("order_detail", args=[order.pk]) + "?tab=finance").content.decode()
        self.assertIn("data-receipt-status", page)
        self.assertIn("款項還沒收清", page)
        self.assertIn("收清後系統會自動標成「已收清」，不用手動勾。", page)
        self.assertNotIn('name="operations-payment_confirmed"', page)
        self.assertIn("跟著訂單的車行；要改請按頁首「變更車行」。", page)
        self.assertNotIn("由訂單或收款紀錄自動同步。", page)

    def test_settled_when_all_receivables_confirmed(self):
        order = self.dealer_order()
        due = payment_summary(order)["customer_due"]
        PaymentRecord.objects.create(order=order, item_name="車行付款", received_amount=due,
                                     received_on=order.created_at.date(), payment_method="現金", confirmed=True)
        status = receipt_status(order, payment_summary(order))
        self.assertTrue(status["settled"])

    def test_unconfirmed_receipt_is_listed(self):
        order = self.dealer_order()
        PaymentRecord.objects.create(order=order, item_name="車行付款", received_amount=Decimal("1000"),
                                     received_on=order.created_at.date(), payment_method="現金", confirmed=False)
        texts = " ".join(item["text"] for item in receipt_status(order, payment_summary(order))["items"])
        self.assertIn("已填實收、還沒勾「已確認」", texts)


def get_root():
    from django.contrib.auth import get_user_model
    return get_user_model().objects.create_superuser("p3-root", password="test-only")
