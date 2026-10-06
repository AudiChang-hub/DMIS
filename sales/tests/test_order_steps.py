from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import DeliveryRecord, PaymentRecord, SalesOrder
from sales.services.order_next_actions import build_order_next_actions
from sales.services.order_steps import build_order_steps, order_step_url
from sales.tests import test_order_lifecycle as lifecycle


class OrderStepTests(TestCase):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order
    delivery_payload = lifecycle.OrderLifecycleTests.delivery_payload

    def registered_v2(self, deposit=Decimal("0")):
        order, vehicle = self.make_order(deposit=deposit)
        SalesOrder.objects.filter(pk=order.pk).update(
            cash_receivable_v2=True, registration_completed_at=timezone.now(), registration_date=date(2026, 8, 4),
            final_plate_number="STP-0001", status=SalesOrder.Status.DELIVERY_PENDING,
        )
        PaymentRecord.objects.filter(order=order, system_key="deposit").update(received_amount=0)
        order.refresh_from_db()
        return order, vehicle

    def test_steps_follow_order_progress_and_next_action(self):
        order, _vehicle = self.make_order(deposit=Decimal("5000"))
        context = build_order_steps(order, next_actions=build_order_next_actions(order))
        steps = context["steps"]
        self.assertEqual([step["key"] for step in context["step_list"]],
                         ["order", "deposit", "documents", "allocation", "registration", "finance", "delivery"])
        self.assertEqual(steps["allocation"]["state"], "done")
        self.assertEqual(steps["deposit"]["state"], "todo")
        self.assertEqual(context["current_step"], "registration")
        self.assertEqual(context["open_step"], "registration")
        self.assertEqual(build_order_steps(order, requested="finance")["open_step"], "finance")

    def test_detail_page_opens_current_step_only(self):
        order, _vehicle = self.registered_v2()
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        self.assertIn('class="order-step is-current is-active" id="panel-delivery"', page)
        self.assertIn('id="tab-delivery" role="tab" aria-controls="panel-delivery" aria-selected="true" tabindex="0"', page)
        self.assertIn('id="tab-registration" role="tab" aria-controls="panel-registration" aria-selected="false" tabindex="-1"', page)
        self.assertNotIn('is-active" id="panel-registration"', page)
        self.assertIn('id="delivery-balance"', page)
        self.assertIn("收尾款並完成交車", page)

    def test_deposit_step_records_and_confirms_deposit(self):
        order, _vehicle = self.make_order(deposit=Decimal("5000"))
        PaymentRecord.objects.filter(order=order, system_key="deposit").update(received_amount=0)
        self.client.force_login(self.user)
        response = self.client.post(reverse("deposit_payment_update", args=[order.pk]), {
            "deposit-received_amount": "5000", "deposit-received_on": "2026-08-01",
            "deposit-payment_method": "現金", "deposit-confirmed": "on",
        })
        self.assertRedirects(response, order_step_url(order.pk, "deposit"))
        deposit = order.payment_records.get(system_key="deposit")
        self.assertTrue(deposit.confirmed)
        self.assertEqual(deposit.received_amount, Decimal("5000"))
        order.refresh_from_db()
        self.assertEqual(build_order_steps(order)["steps"]["deposit"]["state"], "done")

    def section_payload(self, order, section, **values):
        from sales.forms import OrderOperationsForm
        from sales.models import OrderOperationsProfile
        from sales.tests.test_order_workspace import form_data

        profile = OrderOperationsProfile.objects.get(order=order)
        data = form_data(OrderOperationsForm(instance=profile, prefix="operations", section=section))
        data.update({"_section": section, **{f"operations-{k}": v for k, v in values.items()}})
        return data

    def test_step_sections_save_only_their_own_fields(self):
        from sales.models import OrderOperationsProfile
        order, _vehicle = self.make_order()
        OrderOperationsProfile.objects.filter(order=order).update(vehicle_cost=Decimal("50000"), helmet="舊安全帽")
        self.client.force_login(self.user)
        url = reverse("order_operations", args=[order.pk])
        response = self.client.post(url, self.section_payload(order, "fulfillment", helmet="新安全帽"),
                                    HTTP_X_ORDER_WORKSPACE="1")
        self.assertEqual(response.status_code, 200, response.content)
        profile = OrderOperationsProfile.objects.get(order=order)
        self.assertEqual(profile.helmet, "新安全帽")
        self.assertEqual(profile.vehicle_cost, Decimal("50000"))
        self.assertEqual(profile.manual_financial_fields, [])
        response = self.client.post(url, self.section_payload(order, "subsidy", bank_name="測試銀行"),
                                    HTTP_X_ORDER_WORKSPACE="1")
        self.assertEqual(response.status_code, 200, response.content)
        profile.refresh_from_db()
        self.assertEqual((profile.bank_name, profile.helmet), ("測試銀行", "新安全帽"))

    def test_finance_step_groups_internal_fields_under_advanced(self):
        order, _vehicle = self.make_order()
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        finance = page.split('id="panel-finance"', 1)[1].split('id="panel-delivery"', 1)[0]
        self.assertIn("進階：成本、獎勵與傭金", finance)
        self.assertIn('name="_section" value="finance"', finance)
        self.assertNotIn("車控與電池合約", finance)
        self.assertIn("車控與電池合約", page.split('id="panel-delivery"', 1)[1].split('id="panel-subsidy"', 1)[0])

    def test_delivery_collects_balance_in_one_submission(self):
        order, vehicle = self.registered_v2()
        self.client.force_login(self.user)
        payload = {**self.delivery_payload(), "balance-received_amount": "60000",
                   "balance-received_on": "2026-08-05", "balance-payment_method": "現金"}
        self.client.post(reverse("delivery_complete", args=[order.pk]), payload)
        order.refresh_from_db()
        self.assertFalse(order.is_delivered)
        self.assertFalse(order.payment_records.get(system_key="balance").confirmed)
        self.assertFalse(DeliveryRecord.objects.filter(order=order).exists())

        payload["balance-received_amount"] = "75000"
        response = self.client.post(reverse("delivery_complete", args=[order.pk]), payload, follow=True)
        self.assertContains(response, "車輛交付完成")
        order.refresh_from_db()
        balance = order.payment_records.get(system_key="balance")
        self.assertTrue(order.is_delivered)
        self.assertTrue(balance.confirmed)
        self.assertEqual(balance.received_amount, Decimal("75000"))
