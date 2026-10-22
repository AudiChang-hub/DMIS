"""交車不等撥款（使用者 2026-10-22 T-102）：「如果是平台單，就不可能是等到平台撥款才算交車」「分期也是」。

分期公司撥款、平台撥款事後在統一撥款對帳核對；未入帳不擋交車，也不算成客人還欠的錢。
客人應付＝總價－分期金額－訂金－其他已收。交車區不放「前往收入與支出」的導向框，尚未開放時直接列出還差什麼。
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import PaymentRecord, SalesOrder, SalesSource, Store, VehicleInventory
from sales.services.payment_summary import balance_breakdown, payment_summary
from sales.tests import test_payment_splits as split_tests
from sales.tests import test_vehicle_revenue_t62 as t62

splits = split_tests.splits


class DeliveryIgnoresPayoutsTests(TestCase):
    setUp = split_tests.PaymentSplitTests.setUp
    image = split_tests.PaymentSplitTests.image
    complete_data = split_tests.PaymentSplitTests.complete_data
    submit = split_tests.PaymentSplitTests.submit
    create = split_tests.PaymentSplitTests.create
    plan = t62.VehicleRevenueTests.plan

    def installment(self, *rows):
        self.plan()
        return self.create(payment_splits=splits(*rows), plate_insurance_fee="2350", installment_company="和潤",
                           installment_periods="24", installment_monthly="3000")

    def platform(self):
        source, _ = SalesSource.objects.get_or_create(name="Yahoo", source_type="platform")
        return self.create(source_type="platform", source=str(source.pk), payment_splits="", vehicle_price="",
                           plate_insurance_fee="2100")

    def ready(self, order):
        """配車、領牌完成、客人該付的都收妥；撥款列維持未入帳。"""
        store = Store.objects.first() or Store.objects.create(name="T102 門市", code="T102")
        order.allocate(VehicleInventory.objects.create(vehicle_model=self.model, color=self.color,
                                                       engine_number=f"ENG-T102-{order.pk}", ownership_store=store, location_store=store))
        SalesOrder.objects.filter(pk=order.pk).update(registration_completed_at=timezone.now())
        for payment in order.payment_records.exclude(system_key__in=PaymentRecord.PAYOUT_KEYS):
            if payment.expected_amount:
                PaymentRecord.objects.filter(pk=payment.pk).update(received_amount=payment.expected_amount, confirmed=True)
        return SalesOrder.objects.get(pk=order.pk)

    def assert_payouts_do_not_matter(self, order):
        payouts = list(order.payment_records.filter(system_key__in=PaymentRecord.PAYOUT_KEYS))
        self.assertTrue(payouts and not any(p.confirmed for p in payouts))
        records = list(order.payment_records.all())
        summary = payment_summary(order, records)
        without = payment_summary(order, [p for p in records if p.system_key not in PaymentRecord.PAYOUT_KEYS])
        # 客人應付＝總價－分期金額（含訂金與其他已收）；分期公司撥款、平台撥款都不算在客人身上。
        self.assertEqual(summary["customer_expected"], balance_breakdown(order, summary)["total"] - order.installment_split_amount)
        for key in ("customer_expected", "customer_received", "delivery_due", "customer_settled"):
            self.assertEqual(summary[key], without[key], key)
        self.assertTrue(summary["customer_settled"])
        self.assertEqual(order.delivery_blockers(summary, include_prep=False), [])
        self.assertEqual(balance_breakdown(order, summary)["due"], 0)

    def test_platform_order_delivers_while_platform_payout_is_pending(self):
        order = self.ready(self.platform())
        self.assertEqual(order.vehicle_price, 0)
        self.assert_payouts_do_not_matter(order)

    def test_installment_order_delivers_while_lender_payout_is_pending(self):
        order = self.ready(self.installment(("installment", 79800)))
        self.assert_payouts_do_not_matter(order)
        self.assertEqual(order.payment_records.get(system_key="installment_disbursement").expected_amount, Decimal("76608"))

    def test_mixed_payment_order_delivers_while_lender_payout_is_pending(self):
        order = self.ready(self.installment(("installment", 30000), ("cash", 49800)))
        self.assert_payouts_do_not_matter(order)
        self.assertEqual(order.payment_records.get(system_key="installment_disbursement").expected_amount, Decimal("28800"))

    def test_delivery_area_lists_what_is_missing_without_finance_redirect(self):
        order = self.platform()
        page = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "delivery"}).content.decode()
        delivery = page.split('id="panel-delivery"', 1)[1].split('id="panel-subsidy"', 1)[0]
        self.assertIn('id="delivery-pending"', delivery)
        self.assertIn("尚未配車，不能完成交付。", delivery)
        for text in ("前往收入與支出", 'data-workspace-go="finance"', "尾款已收清或由車行掛帳", 'id="delivery-payment"', "撥款"):
            self.assertNotIn(text, delivery)
