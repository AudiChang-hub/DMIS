"""1.69.0：現階段訂單都由本店處理——建立人直接接單、代合作車行開單不需公司確認。"""
from django.urls import reverse

from django.test import TestCase

from sales.models import SalesOrder
from sales.tests import test_order_intake as intake_fixtures


class StoreHandlesOrdersTests(TestCase):
    image = intake_fixtures.OrderIntakeTests.image
    complete_data = intake_fixtures.OrderIntakeTests.complete_data
    setUp = intake_fixtures.OrderIntakeTests.setUp

    def submit(self, url_name="order_create", **changes):
        data = self.complete_data()
        data.update(id_front=self.image("front.png"), id_back=self.image("back.png"))
        data.update(changes)
        return self.client.post(reverse(url_name), data)

    def test_creator_accepts_order_immediately(self):
        page = self.client.get(reverse("order_create")).content.decode()
        self.assertNotIn("intake-accept-card", page)
        response = self.submit()
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        order = SalesOrder.objects.get()
        self.assertEqual(order.status, SalesOrder.Status.ALLOCATION_PENDING)
        self.assertEqual(order.accepted_by, self.user)
        self.assertTrue(order.events.filter(event_type="accepted").exists())

    def test_dealer_source_needs_no_company_confirmation_and_uses_store_company(self):
        self.client.force_login(self.root)
        page = self.client.get(reverse("order_start")).content.decode()
        self.assertNotIn("data-assisted-company", page)
        self.assertNotIn("assisted-companies", page)
        response = self.submit("order_start", source_type="dealer", source=str(self.dealer.pk))
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        order = SalesOrder.objects.get()
        self.assertEqual(order.source_id, self.dealer.pk)
        self.assertEqual(order.print_company_snapshot["legal_name"], "馭盛國際有限公司")
        self.assertEqual(order.status, SalesOrder.Status.ALLOCATION_PENDING)

    def test_dealer_account_orders_still_wait_for_store(self):
        self.client.force_login(self.dealer_user)
        response = self.submit()
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        self.assertEqual(SalesOrder.objects.get().status, SalesOrder.Status.INTAKE_PENDING)
