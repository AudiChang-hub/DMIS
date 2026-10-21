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

    def test_gas_vehicle_has_no_prep_confirmation(self):
        # 「贈品與履約」整區拿掉，不再是交車條件（使用者 2026-10-21 T-57）。
        order, _vehicle = self.make_order()
        self.clear_confirmations(order)
        blockers = order.delivery_blockers(ignore_balance=True)
        self.assertFalse(any("贈品與履約" in item for item in blockers))
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
        VehicleModel.objects.filter(pk=self.model.pk).update(energy_type=VehicleModel.EnergyType.ELECTRIC)
        self.clear_confirmations(order)
        profile = order.operations
        url = reverse("order_operations", args=[order.pk])
        payload = {"_section": "fulfillment", "operations-financial_revision": profile.updated_at.isoformat(),
                   "operations-vehicle_control_confirmed": "on", "operations-fulfillment_confirmed": "on"}
        self.client.post(url, payload)
        profile.refresh_from_db()
        self.assertIsNotNone(profile.vehicle_control_confirmed_at)
        self.assertTrue(profile.vehicle_control_confirmed_by)
        # 贈品與履約已不在表單上，送來的勾選不會寫入（T-57）。
        self.assertIsNone(profile.fulfillment_confirmed_at)
        payload = {"_section": "fulfillment", "operations-financial_revision": profile.updated_at.isoformat()}
        self.client.post(url, payload)
        profile.refresh_from_db()
        self.assertIsNone(profile.vehicle_control_confirmed_at)

    def test_gift_fields_are_kept_but_no_longer_edited(self):
        order, _vehicle = self.make_order()
        OrderOperationsProfile.objects.filter(order=order).update(helmet="原有安全帽", platform_gift="原有平台贈品")
        from sales.forms import OrderOperationsForm
        for section in (None, "finance", "fulfillment"):
            form = OrderOperationsForm(instance=order.operations, prefix="operations", section=section)
            for name in ("helmet", "company_gift_or_remittance", "platform_gift", "other_fulfillment",
                         "customer_service_phone", "fulfillment_confirmed"):
                self.assertNotIn(name, form.fields, (section, name))
        profile = OrderOperationsProfile.objects.get(order=order)
        self.assertEqual((profile.helmet, profile.platform_gift), ("原有安全帽", "原有平台贈品"))
