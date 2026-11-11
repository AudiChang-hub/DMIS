"""車控帳號／密碼的預設帶入（使用者 2026-11-11 T-144；密碼預設 2026-10-15）。"""

from django.urls import reverse

from sales.forms import OrderOperationsForm
from sales.models import OrderOperationsProfile, SalesOrder
from sales.tests import test_order_lifecycle as lifecycle


class VehicleControlDefaultTests(lifecycle.OrderLifecycleTests.__bases__[0]):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def form_for(self, email="abc@123.com", account=""):
        order, _vehicle = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(owner_email=email)
        OrderOperationsProfile.objects.filter(order=order).update(vehicle_control_account=account)
        profile = OrderOperationsProfile.objects.get(order=order)
        return OrderOperationsForm(instance=profile, prefix="operations", section="fulfillment")

    def test_blank_account_defaults_to_email_local_part(self):
        form = self.form_for(email="abc@123.com")
        self.assertEqual(form["vehicle_control_account"].value(), "abc")
        self.assertIn('value="abc"', str(form["vehicle_control_account"]))

    def test_blank_or_invalid_email_gives_no_default(self):
        for email in ("", "abc.123.com", "@123.com"):
            form = self.form_for(email=email)
            self.assertIn(form["vehicle_control_account"].value(), ("", None), email)

    def test_existing_account_is_not_overwritten(self):
        form = self.form_for(email="abc@123.com", account="saved-account")
        self.assertEqual(form["vehicle_control_account"].value(), "saved-account")

    def test_default_is_saved_and_editable(self):
        from django.contrib.auth import get_user_model

        admin = get_user_model().objects.create_superuser("admin", password="Ctrl-account-test-144!")
        self.client.force_login(admin)
        order, _vehicle = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(owner_email="abc@123.com")
        profile = OrderOperationsProfile.objects.get(order=order)
        url = reverse("order_operations", args=[order.pk])
        self.client.post(url, {
            "_section": "fulfillment", "operations-financial_revision": profile.updated_at.isoformat(),
            "operations-vehicle_control_account": "edited",
        })
        profile.refresh_from_db()
        self.assertEqual(profile.vehicle_control_account, "edited")

    def test_password_default_still_uses_owner_phone(self):
        form = self.form_for(email="abc@123.com")
        field = form.fields["vehicle_control_password"]
        self.assertEqual(field.initial, "0912345678")
        self.assertEqual(field.help_text, "預設為新車主手機號碼，可直接修改；儲存後加密保存。")
        self.assertNotIn("abc", str(form["vehicle_control_password"]))
