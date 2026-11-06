"""UAT 2026-11（使用者 2026-11-06 選 A）：
U-02 分期單建立後就帶入預估車價收入，不必等領牌；U-03 交車收尾款看交車（work）權限，不需內部財務權限。"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import OrderOperationsProfile, PaymentRecord, SalesOrder
from sales.services.operations_sync import sync_order_operations
from sales.services.payment_summary import payment_summary
from sales.tests import test_order_lifecycle as lifecycle
from sales.tests import test_order_steps as steps
from sales.tests.test_delivery_balance_t73 import delivery_panel


class InstallmentRevenueEstimateTests(TestCase):
    setUp = steps.OrderStepTests.setUp
    make_order = steps.OrderStepTests.make_order

    def installment(self, expected="74214"):
        order, _vehicle = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(
            payment_type=SalesOrder.PaymentType.INSTALLMENT,
            payment_splits=[{"method": SalesOrder.PaymentSplitMethod.INSTALLMENT.value, "amount": str(order.vehicle_price)}],
            installment_plan_snapshot={"expected_disbursement_amount": expected},
        )
        sync_order_operations(order.pk)
        return SalesOrder.objects.get(pk=order.pk)

    def profile(self, order):
        return OrderOperationsProfile.objects.get(order=order)

    def test_estimate_is_written_before_registration(self):
        order = self.installment()
        self.assertIsNone(order.registration_completed_at)
        self.assertEqual(self.profile(order).actual_disbursement, Decimal("74214"))

    def test_manual_value_and_reconciled_value_are_kept(self):
        order = self.installment()
        OrderOperationsProfile.objects.filter(order=order).update(
            actual_disbursement=Decimal("70000"), manual_financial_fields=["actual_disbursement"])
        sync_order_operations(order.pk)
        self.assertEqual(self.profile(order).actual_disbursement, Decimal("70000"))
        OrderOperationsProfile.objects.filter(order=order).update(
            actual_disbursement=Decimal("73000"), manual_financial_fields=[], payment_disbursement_snapshot={"applied": "73000"})
        sync_order_operations(order.pk)
        self.assertEqual(self.profile(order).actual_disbursement, Decimal("73000"))

    def test_without_rate_keeps_current_value(self):
        order = self.installment(expected=None)
        OrderOperationsProfile.objects.filter(order=order).update(actual_disbursement=Decimal("0"))
        SalesOrder.objects.filter(pk=order.pk).update(installment_plan_snapshot={})
        sync_order_operations(order.pk)
        self.assertEqual(self.profile(order).actual_disbursement, Decimal("0"))


class WorkOnlyDeliveryBalanceTests(TestCase):
    setUp = steps.OrderStepTests.setUp
    make_order = steps.OrderStepTests.make_order
    registered_v2 = steps.OrderStepTests.registered_v2
    delivery_payload = lifecycle.OrderLifecycleTests.delivery_payload

    def account(self, *screens):
        user = get_user_model().objects.create_user(f"qa-{'-'.join(screens) or 'none'}", password="test-only")
        UserAccessState.objects.create(user=user, configured=True)
        for key in ("orders", *screens):
            ScreenAccessGrant.objects.create(user=user, screen_key=key, view=True, operate=True)
        return user

    def test_work_only_account_sees_balance_and_completes_delivery(self):
        order, _vehicle = self.registered_v2()
        self.client.force_login(self.account("work"))
        page = self.client.get(reverse("order_detail", args=[order.pk]))
        self.assertEqual(page.status_code, 200)
        delivery = delivery_panel(page.content.decode())
        self.assertIn('id="delivery-balance"', delivery)
        self.assertIn("收尾款並完成交車", delivery)
        self.assertNotIn("收入與支出", " ".join(page.context["delivery_blockers"]))
        due = payment_summary(order)["delivery_due"]
        self.client.post(reverse("delivery_complete", args=[order.pk]), {
            **self.delivery_payload(), "balance-received_amount": str(due), "balance-received_on": "2026-10-22",
            "balance-payment_method": "現金"}, follow=True)
        order.refresh_from_db()
        self.assertTrue(order.is_delivered)
        self.assertTrue(PaymentRecord.objects.get(order=order, system_key="balance").confirmed)

    def test_account_without_delivery_right_is_told_who_can_collect(self):
        from django.test import RequestFactory
        from sales.services.order_workspace import delivery_gate
        order, _vehicle = self.registered_v2()
        request = RequestFactory().get("/")
        request.user = self.account()
        collect, blockers = delivery_gate(request, order)
        self.assertFalse(collect)
        self.assertTrue(any("請有交車權限的人員" in text for text in blockers), blockers)
        self.assertFalse(any("收入與支出" in text for text in blockers), blockers)
