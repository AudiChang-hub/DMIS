"""T-191：進階篩選欄名固定「車行／平台」、使用指南改用新名稱、KPI 刪除重複特例；KPI 標題結果不變。"""
import inspect
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import ReportDefinition, SalesOrder, SalesSource, VehicleColor, VehicleModel
from sales.reporting import kpis
from sales.reporting.forms import FilterForm
from sales.reporting.source_templates import dealer_counts, dealer_sales, electric_platform_sales

OLD = "原報表車行／平台名稱"


def standard(config, legacy_source=None):
    config = {**config, "audience": "team", "reader_layout": "standard"}
    scope = {key: value for key, value in config["fixed_filters"].items() if key != "legacy_source"}
    if legacy_source:
        scope["legacy_source"] = legacy_source
    config["fixed_filters"] = scope
    return config


class DealerLabelPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", "admin@example.invalid", "Test-Only-123")
        electric = VehicleModel.objects.create(brand="eReady", name="Fun", model_number="EV060L", energy_type="electric")
        dealer = SalesSource.objects.create(name="甲車行", source_type="dealer")
        platform = SalesSource.objects.create(name="MOMO", source_type="platform")
        for source_type, source in (("dealer", dealer), ("platform", platform)):
            color = VehicleColor.objects.create(vehicle_model=electric, name=f"白{source_type}")
            SalesOrder.objects.create(source_type=source_type, source=source, order_date=date(2026, 10, 2),
                registration_date=date(2026, 10, 3), registration_completed_at=timezone.now(),
                owner_type="company", owner_name="合成車主", owner_id_number="83739807",
                vehicle_model=electric, color=color, vehicle_price=10000, actual_balance=10000,
                calculated_balance=10000, payment_type="cash", status="completed")
        configs = {
            "dealer": {**dealer_sales(), "audience": "team"},
            "count": {**dealer_counts(), "audience": "team"},
            "platform": {**electric_platform_sales(), "audience": "team"},
            "std_none": standard(dealer_sales()),
            "std_dealer": standard(dealer_sales(), ["車行"]),
            "std_platform": standard(dealer_sales(), ["網路平台"]),
            "std_both": standard(dealer_sales(), ["車行", "網路平台"]),
        }
        cls.reports = {key: ReportDefinition.objects.create(draft=config, published=config, version=1)
                       for key, config in configs.items()}

    def setUp(self):
        self.client.force_login(self.admin)

    def get(self, key):
        response = self.client.get(reverse("report_display", args=[self.reports[key].pk]))
        self.assertEqual(response.status_code, 200)
        return response

    def test_advanced_filter_label_is_always_neutral(self):
        # 使用者選 B：一般版型進階區固定「車行／平台」，不跟著固定條件變，避免和上方「車行」選單同名。
        for key in ("std_none", "std_dealer", "std_platform", "std_both"):
            with self.subTest(report=key):
                response = self.get(key)
                self.assertEqual(response.context["filter_form"]["legacy_dealer"].label, "車行／平台")
                self.assertContains(response, '<label for="id_legacy_dealer">車行／平台</label>', html=False)
                self.assertContains(response, '<label for="id_source_dealer">車行</label>', html=False)
                self.assertNotContains(response, OLD)

    def test_reader_layouts_keep_their_split_pickers(self):
        for key in ("dealer", "count", "platform"):
            with self.subTest(report=key):
                form = self.get(key).context["filter_form"]
                self.assertEqual(form["legacy_dealer"].label, "車行／平台")
                self.assertTrue(form["legacy_dealer"].split_groups)

    def test_filter_form_without_config_is_neutral(self):
        self.assertEqual(FilterForm().fields["legacy_dealer"].label, "車行／平台")

    def test_kpi_titles_are_unchanged(self):
        expected = {"dealer": "最多的車行", "std_dealer": "最多的車行", "std_platform": "最多的平台",
                    "std_none": "最多的車行／平台", "std_both": "最多的車行／平台"}
        for key, title in expected.items():
            with self.subTest(report=key):
                labels = [tile["label"] for tile in self.get(key).context["kpis"]]
                self.assertIn(title, labels)
                self.assertFalse(any(OLD in label for label in labels))
        # 依月份分的平台頁與台數頁維持原本的摘要格。
        self.assertEqual([tile["label"] for tile in self.get("platform").context["kpis"]][:2], ["訂單", "單月最高"])
        self.assertIn("車行數", [tile["label"] for tile in self.get("count").context["kpis"]])

    def test_kpis_no_longer_carry_their_own_dealer_rule(self):
        self.assertFalse(hasattr(kpis, "SCOPED_DEALER_LABELS"))
        self.assertEqual(list(inspect.signature(kpis.reader_kpis).parameters), ["results"])


class UserGuideTests(TestCase):
    def test_guide_uses_current_screen_names(self):
        guide = (Path(settings.BASE_DIR) / "templates" / "help" / "user_guide.html").read_text(encoding="utf-8")
        self.assertNotIn(OLD, guide)
        self.assertIn("「車行／平台」分類（只算車行的頁面顯示「車行」、只算網路平台的顯示「平台」）", guide)
