"""T-188：KPI「最多的…」標題依報表固定的銷售來源命名，不顯示「原報表車行／平台名稱」。"""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import ReportDefinition, SalesOrder, SalesSource, VehicleColor, VehicleModel
from sales.reporting.engine import display_dimension
from sales.reporting.kpis import reader_kpis
from sales.reporting.source_templates import dealer_counts, dealer_sales, electric_platform_sales


def result(dimension, label="原報表車行／平台名稱（比對用）"):
    return {"card": {"chart": "stacked", "dimension": dimension, "metric": "count", "fixed_filters": {}},
            "count": 5, "dimension_label": label,
            "rows": [{"label": "甲車行", "value": "3", "display": "3", "percentage": 60.0},
                     {"label": "乙車行", "value": "2", "display": "2", "percentage": 40.0}]}


class PeakLabelTests(SimpleTestCase):
    # T-191：KPI 不再自帶特例，名稱來自圖卡結果的 dimension_label（engine.display_dimension）。
    def peak(self, dimension, fixed_filters):
        label = display_dimension(dimension, {"fixed_filters": fixed_filters})
        return [tile["label"] for tile in reader_kpis([result(dimension, label)]) if tile["label"].startswith("最多的")]

    def test_dealer_label_follows_fixed_sales_source(self):
        self.assertEqual(self.peak("legacy_dealer", {"legacy_source": ["車行"]}), ["最多的車行"])
        self.assertEqual(self.peak("legacy_dealer", {"legacy_source": ["網路平台"]}), ["最多的平台"])

    def test_other_pages_and_dimensions_keep_the_dimension_label(self):
        # T-189 起不限來源顯示中性名稱「車行／平台」。
        self.assertEqual(self.peak("legacy_dealer", {}), ["最多的車行／平台"])
        self.assertEqual(self.peak("legacy_dealer", {"legacy_source": ["車行", "網路平台"]}), ["最多的車行／平台"])
        self.assertEqual(self.peak("brand", {"legacy_source": ["車行"]}), ["最多的品牌"])
        self.assertEqual(self.peak("legacy_sales_source", {}), ["最多的銷售來源"])


class ReportPageKpiTitleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", "admin@example.invalid", "Test-Only-123")
        electric = VehicleModel.objects.create(brand="eReady", name="Fun", model_number="EV060L", energy_type="electric")
        gas = VehicleModel.objects.create(brand="SUZUKI", name="Saluto", model_number="UC125", energy_type="gas")
        dealer = SalesSource.objects.create(name="甲車行", source_type="dealer")
        platform = SalesSource.objects.create(name="MOMO", source_type="platform")
        for model, source_type, source in ((electric, "dealer", dealer), (electric, "platform", platform), (gas, "dealer", dealer)):
            color = VehicleColor.objects.create(vehicle_model=model, name=f"白{source_type}{model.pk}")
            SalesOrder.objects.create(source_type=source_type, source=source, order_date=date(2026, 10, 2),
                registration_date=date(2026, 10, 3), registration_completed_at=timezone.now(),
                owner_type="company", owner_name="合成車主", owner_id_number="83739807",
                vehicle_model=model, color=color, vehicle_price=10000, actual_balance=10000,
                calculated_balance=10000, payment_type="cash", status="completed")
        cls.reports = {}
        for key, config in (("4", electric_platform_sales()), ("9", dealer_sales()), ("12", dealer_counts(gasoline=True))):
            config = {**config, "audience": "team"}
            cls.reports[key] = ReportDefinition.objects.create(draft=config, published=config, version=1)

    def labels(self, key):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("report_display", args=[self.reports[key].pk]))
        self.assertEqual(response.status_code, 200)
        return [tile["label"] for tile in response.context["kpis"]]

    def test_dealer_page_says_most_dealer(self):
        labels = self.labels("9")
        self.assertIn("最多的車行", labels)
        self.assertFalse(any("原報表" in label for label in labels))

    def test_platform_and_count_pages_have_no_legacy_title(self):
        # 平台頁的圖依月份分，摘要是「單月最高」；台數頁是「車行數」，兩頁都不會出現舊名稱。
        for key in ("4", "12"):
            with self.subTest(report=key):
                labels = self.labels(key)
                self.assertFalse(any("原報表" in label for label in labels), labels)
        self.assertIn("車行數", self.labels("12"))
