"""車控帳號／密碼的預設帶入（使用者 2026-11-11 T-144；密碼預設 2026-10-15）。"""

import importlib

from django.apps import apps
from django.urls import reverse

from sales.forms import OrderOperationsForm
from sales.models import OrderOperationsProfile, SalesOrder, VehicleModel
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


backfill = importlib.import_module("sales.migrations.0200_backfill_vehicle_control_account")


class VehicleControlAccountBackfillTests(lifecycle.OrderLifecycleTests.__bases__[0]):
    """0200 資料 migration：既有電動車訂單空白車控帳號補上車主 Email 前綴（使用者 2026-11-11 T-144 方案 A）。"""

    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def profile(self, email, account="", electric=True):
        order, _vehicle = self.make_order()
        if electric:
            ev_model, _created = VehicleModel.objects.get_or_create(
                brand="SUZUKI", name="EV 測試", model_number="EV1", model_year=2026, model_code="ev",
                defaults={"displacement_cc": 0, "energy_type": VehicleModel.EnergyType.ELECTRIC})
            SalesOrder.objects.filter(pk=order.pk).update(vehicle_model=ev_model)
        SalesOrder.objects.filter(pk=order.pk).update(owner_email=email)
        OrderOperationsProfile.objects.filter(order=order).update(vehicle_control_account=account)
        return OrderOperationsProfile.objects.get(order=order)

    def account(self, profile):
        profile.refresh_from_db()
        return profile.vehicle_control_account

    def test_backfill_cases_and_idempotent(self):
        blank = self.profile("abc@123.com")
        multi_at = self.profile(" first@x@y.com ")
        kept = self.profile("abc@123.com", account="saved-account")
        no_email = self.profile("")
        no_at = self.profile("abc.123.com")
        gas = self.profile("gas@123.com", electric=False)

        self.assertEqual(backfill.backfill_accounts(apps), 2)
        self.assertEqual(self.account(blank), "abc")
        self.assertEqual(self.account(multi_at), "first")
        self.assertEqual(self.account(kept), "saved-account")
        self.assertEqual(self.account(no_email), "")
        self.assertEqual(self.account(no_at), "")
        self.assertEqual(self.account(gas), "")
        # 重跑不會再改任何一筆。
        self.assertEqual(backfill.backfill_accounts(apps), 0)
        self.assertEqual(self.account(blank), "abc")

    def test_reverse_only_clears_values_equal_to_email_prefix(self):
        blank = self.profile("abc@123.com")
        kept = self.profile("abc@123.com", account="saved-account")
        gas = self.profile("gas@123.com", account="gas", electric=False)
        backfill.backfill_accounts(apps)

        self.assertEqual(backfill.clear_backfilled_accounts(apps), 1)
        self.assertEqual(self.account(blank), "")
        self.assertEqual(self.account(kept), "saved-account")
        self.assertEqual(self.account(gas), "gas")
