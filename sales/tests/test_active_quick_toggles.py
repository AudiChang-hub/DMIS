from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import InstallmentCompany


class ActiveQuickToggleTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="active-toggle-user",
            password="TogglePass!12345",
        )
        self.client.force_login(self.user)

    def test_master_record_toggle_updates_in_place_payload(self):
        company = InstallmentCompany.objects.create(name="快速切換分期公司")
        url = reverse(
            "master_record_set_active",
            args=["installment-company", company.pk],
        )

        response = self.client.post(
            url,
            {"active": "0"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "ok": True,
                "active": False,
                "resource": "installment-company",
                "pk": company.pk,
                "message": "分期公司「快速切換分期公司」已停用。",
            },
        )
        company.refresh_from_db()
        self.assertFalse(company.active)

    def test_master_record_toggle_rejects_invalid_state_without_change(self):
        company = InstallmentCompany.objects.create(name="保留狀態分期公司")

        response = self.client.post(
            reverse(
                "master_record_set_active",
                args=["installment-company", company.pk],
            ),
            {"active": "unexpected"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        company.refresh_from_db()
        self.assertTrue(company.active)

    def test_master_record_toggle_rejects_unknown_resource(self):
        response = self.client.post(
            reverse("master_record_set_active", args=["unknown", 1]),
            {"active": "0"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json()["ok"])

    def test_shared_quick_toggle_never_depends_on_native_form_navigation(self):
        template = (
            Path(settings.BASE_DIR) / "templates" / "sales" / "_active_quick_toggle.html"
        ).read_text(encoding="utf-8")
        script = (
            Path(settings.BASE_DIR) / "static" / "js" / "active-quick-toggle.js"
        ).read_text(encoding="utf-8")

        self.assertIn('type="button"', template)
        self.assertIn('document.addEventListener("click"', script)
        self.assertIn('window.addEventListener("pageshow", resetPendingToggles)', script)

    def test_all_master_status_lists_use_shared_quick_toggle(self):
        expected_resources = {
            "accessory_product_list.html": "accessory-product",
            "brand_registration_fee_rule_list.html": "brand-registration-fee-rule",
            "business_holiday_list.html": "business-holiday",
            "dealer_volume_bonus_list.html": "dealer-volume-bonus",
            "dealer_reward_catalog_list.html": "dealer-reward-catalog-item",
            "incentive_rule_list.html": "incentive-rule",
            "installment_company_list.html": "installment-company",
            "installment_plan_list.html": "installment-plan",
            "positioned_template_list.html": "positioned-print-template",
            "sales_source_category_list.html": "sales-source-category",
            "sales_source_holiday_gift_manage.html": "sales-source",
            "sales_source_simple_list.html": "sales-source",
            "settlement_cost_rule_list.html": "settlement-cost-rule",
            "user_management.html": "user-account",
            "vehicle_brand_list.html": "vehicle-brand",
            "vehicle_model_price_versions.html": "vehicle-price-version",
            "_sales_source_rows.html": "sales-source",
            "_vehicle_model_year_cells.html": "vehicle-model",
            "_vehicle_model_year_panel.html": "vehicle-model",
        }
        template_root = Path(settings.BASE_DIR) / "templates" / "sales"

        for template_name, resource in expected_resources.items():
            with self.subTest(template=template_name):
                content = (template_root / template_name).read_text(encoding="utf-8")
                self.assertIn("_active_quick_toggle.html", content)
                self.assertIn(f'resource="{resource}"', content)
