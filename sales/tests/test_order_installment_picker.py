from datetime import date
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from sales.models import InstallmentCompany, InstallmentPlanOption, InstallmentPlanVersion, ScreenAccessGrant, UserAccessState


class OrderInstallmentPickerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from sales.tests.test_completed_order_corrections import CompletedOrderCorrectionTests
        CompletedOrderCorrectionTests.setUpTestData.__func__(cls)
        cls.company = InstallmentCompany.objects.create(name="舊分期公司")
        cls.old_version = InstallmentPlanVersion.objects.create(vehicle_model=cls.model, effective_from=date(2025, 1, 1), effective_to=date(2025, 12, 31))
        cls.new_version = InstallmentPlanVersion.objects.create(vehicle_model=cls.model, effective_from=date(2026, 1, 1))
        cls.old_option = InstallmentPlanOption.objects.create(version=cls.old_version, periods=12, company=cls.company, monthly_amount=6100, opening_fee=500)
        cls.new_option = InstallmentPlanOption.objects.create(version=cls.new_version, periods=24, company=cls.company, monthly_amount=3200, opening_fee=800)

    def setUp(self):
        self.client.force_login(self.user)

    def order(self):
        from sales.tests.test_completed_order_corrections import CompletedOrderCorrectionTests
        return CompletedOrderCorrectionTests.order(self, order_date=date(2025, 9, 1), payment_type="installment",
                    installment_company=self.company.name, installment_periods=12, installment_monthly=6000,
                    installment_opening_fee=0, installment_plan_snapshot={"periods": 12, "company": self.company.name, "historical": True})

    def test_old_order_date_wins_over_today_and_supplied_date(self):
        order = self.order()
        response = self.client.get(reverse("installment_plan_options"), {"vehicle_model": self.model.pk, "order_id": order.pk, "order_date": "2026-09-01"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["order_date"], "2025-09-01")
        self.assertEqual(response.json()["version"]["id"], self.old_version.pk)
        self.assertEqual([row["periods"] for row in response.json()["options"]], [12])

    def test_no_effective_version_does_not_fall_back_to_today(self):
        order = self.order()
        self.old_version.active = False
        self.old_version.save()
        data = self.client.get(reverse("installment_plan_options"), {"vehicle_model": self.model.pk, "order_id": order.pk}).json()
        self.assertEqual(data["options"], [])
        self.assertEqual(data["order_date"], "2025-09-01")

    def test_note_edit_preserves_historical_amounts_zero_fee_and_snapshot(self):
        from sales.tests.test_completed_order_corrections import CompletedOrderCorrectionTests
        order = self.order()
        payload = CompletedOrderCorrectionTests.payload(self, order)
        with patch("sales.views.apply_order_installment_snapshot") as snapshot:
            response = self.client.post(reverse("order_edit", args=[order.pk]), payload)
        self.assertEqual(response.status_code, 302, getattr(response, "context", None))
        snapshot.assert_not_called()
        order.refresh_from_db()
        self.assertEqual(order.installment_monthly, 6000)
        self.assertEqual(order.installment_opening_fee, 0)
        self.assertTrue(order.installment_plan_snapshot["historical"])

    def test_selected_option_rebuilds_snapshot_using_original_date(self):
        from sales.tests.test_completed_order_corrections import CompletedOrderCorrectionTests
        order = self.order()
        payload = CompletedOrderCorrectionTests.payload(self, order, installment_monthly="6100", installment_opening_fee="500")
        response = self.client.post(reverse("order_edit", args=[order.pk]), payload)
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.installment_plan_snapshot["option_id"], self.old_option.pk)
        self.assertEqual(order.installment_monthly, 6100)

    def test_order_lookup_requires_order_access_and_valid_identifier(self):
        order = self.order()
        self.assertEqual(self.client.get(reverse("installment_plan_options"), {"order_id": "bad"}).status_code, 400)
        UserAccessState.objects.create(user=self.user, configured=True)
        ScreenAccessGrant.objects.create(user=self.user, screen_key="models", view=True)
        self.assertEqual(self.client.get(reverse("installment_plan_options"), {"vehicle_model": self.model.pk}).status_code, 200)
        self.assertEqual(self.client.get(reverse("installment_plan_options"), {"vehicle_model": self.model.pk, "order_id": order.pk}).status_code, 403)
