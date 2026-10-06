from django.urls import reverse

from sales.models import OrderOperationsProfile, VehicleModel
from sales.tests import test_order_lifecycle as lifecycle


class DeliveryPrepTests(lifecycle.OrderLifecycleTests.__bases__[0]):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def clear_confirmations(self, order):
        OrderOperationsProfile.objects.filter(order=order).update(
            vehicle_control_confirmed_at=None, vehicle_control_confirmed_by="",
            fulfillment_confirmed_at=None, fulfillment_confirmed_by="")
        order.refresh_from_db()

    def test_gas_vehicle_requires_only_fulfillment_confirmation(self):
        order, _vehicle = self.make_order()
        self.clear_confirmations(order)
        blockers = order.delivery_blockers(ignore_balance=True)
        self.assertIn("請先在「交車前確認」勾選「贈品與履約已確認」。", blockers)
        self.assertFalse(any("車控" in item for item in blockers))

    def test_electric_vehicle_requires_vehicle_control_confirmation(self):
        order, _vehicle = self.make_order()
        VehicleModel.objects.filter(pk=self.model.pk).update(energy_type=VehicleModel.EnergyType.ELECTRIC)
        self.clear_confirmations(order)
        self.assertIn("電動車須先在「交車前確認」勾選「車控與電池合約已確認」。", order.delivery_blockers(ignore_balance=True))

    def test_checkbox_records_and_clears_confirmation(self):
        from django.contrib.auth import get_user_model

        admin = get_user_model().objects.create_superuser("admin", password="Prep-confirm-test-61!")
        self.client.force_login(admin)
        order, _vehicle = self.make_order()
        self.clear_confirmations(order)
        profile = order.operations
        url = reverse("order_operations", args=[order.pk])
        payload = {"_section": "fulfillment", "operations-financial_revision": profile.updated_at.isoformat(),
                   "operations-fulfillment_confirmed": "on"}
        self.client.post(url, payload)
        profile.refresh_from_db()
        self.assertIsNotNone(profile.fulfillment_confirmed_at)
        self.assertTrue(profile.fulfillment_confirmed_by)
        payload = {"_section": "fulfillment", "operations-financial_revision": profile.updated_at.isoformat()}
        self.client.post(url, payload)
        profile.refresh_from_db()
        self.assertIsNone(profile.fulfillment_confirmed_at)
