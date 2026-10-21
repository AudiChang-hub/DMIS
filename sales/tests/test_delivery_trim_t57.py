"""第四版投影片線 A（使用者 2026-10-21）：T-57 交車步驟拿掉贈品與履約；T-64 交車收尾款拿掉非重複確認與收款帳戶。"""
from datetime import date

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.forms import DeliveryPaymentForm
from sales.models import PaymentRecord
from sales.tests import test_order_steps as steps


class DeliveryTrimTests(TestCase):
    setUp = steps.OrderStepTests.setUp
    make_order = steps.OrderStepTests.make_order
    registered_v2 = steps.OrderStepTests.registered_v2

    def test_delivery_step_has_no_gift_section(self):
        order, _vehicle = self.registered_v2()
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        delivery = page.split('id="panel-delivery"', 1)[1].split('id="panel-subsidy"', 1)[0]
        for removed in ("贈品與履約", 'name="operations-helmet"', 'name="operations-platform_gift"',
                        'name="operations-customer_service_phone"', "operations-fulfillment_confirmed"):
            self.assertNotIn(removed, delivery)
        self.assertIn("交車前確認", delivery)
        self.assertIn("已核對配件與贈品", delivery)

    def test_balance_in_delivery_form_has_no_duplicate_or_account_fields(self):
        order, _vehicle = self.registered_v2()
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        fieldset = page.split('id="delivery-balance"', 1)[1].split("</fieldset>", 1)[0]
        for removed in ("balance-duplicate_confirmed", "確認非重複收款", "balance-receiving_account", "收款帳戶"):
            self.assertNotIn(removed, fieldset)
        for kept in ("balance-received_amount", "balance-proof", "balance-note"):
            self.assertIn(kept, fieldset)

    def test_same_day_same_amount_balance_is_not_blocked(self):
        order, _vehicle = self.registered_v2()
        balance = PaymentRecord.objects.get(order=order, system_key="balance")
        today = timezone.localdate()
        PaymentRecord.objects.create(order=order, item_name="另一筆", received_amount=balance.expected_amount,
                                     received_on=today, payment_method="現金", confirmed=True)
        balance.refresh_from_db()
        form = DeliveryPaymentForm(data={"received_amount": str(balance.expected_amount), "received_on": today.isoformat(),
                                         "payment_method": "現金", "confirmed": "on"}, instance=balance)
        self.assertTrue(form.is_valid(), form.errors)

    def test_existing_receiving_account_is_kept(self):
        order, _vehicle = self.registered_v2()
        balance = PaymentRecord.objects.get(order=order, system_key="balance")
        PaymentRecord.objects.filter(pk=balance.pk).update(receiving_account="12345")
        balance.refresh_from_db()
        form = DeliveryPaymentForm(data={"received_amount": str(balance.expected_amount), "received_on": date(2026, 10, 21).isoformat(),
                                         "payment_method": "匯款", "confirmed": "on"}, instance=balance)
        self.assertTrue(form.is_valid(), form.errors)
        form.save("交車人員")
        self.assertEqual(PaymentRecord.objects.get(pk=balance.pk).receiving_account, "12345")
