"""T-189：「原報表車行／平台名稱」依頁面固定條件顯示「車行」「平台」或「車行／平台」，畫面與圖表 CSV 一致。"""
import re
from datetime import date

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import ReportDefinition, SalesOrder, SalesSource, VehicleColor, VehicleModel
from sales.reporting.engine import DIMENSIONS, display_dimension
from sales.reporting.forms import CardForm, designer_dimension_choices
from sales.reporting.source_templates import (dealer_counts, dealer_sales, electric_platform_sales,
                                              gasoline_platform_sales)

OLD = "原報表車行／平台名稱"


class DisplayDimensionTests(SimpleTestCase):
    def test_label_follows_fixed_sales_source(self):
        self.assertEqual(display_dimension("legacy_dealer", {"fixed_filters": {"legacy_source": ["車行"]}}), "車行")
        self.assertEqual(display_dimension("legacy_dealer", {"fixed_filters": {"legacy_source": ["網路平台"]}}), "平台")

    def test_no_restriction_or_both_is_neutral(self):
        self.assertEqual(display_dimension("legacy_dealer", {"fixed_filters": {}}), "車行／平台")
        self.assertEqual(display_dimension("legacy_dealer"), "車行／平台")
        both = {"fixed_filters": {"legacy_source": ["車行", "網路平台"]}}
        self.assertEqual(display_dimension("legacy_dealer", both), "車行／平台")
        self.assertEqual(display_dimension("legacy_dealer", {"fixed_filters": {"legacy_source": ["馭盛"]}}), "車行／平台")

    def test_card_scope_narrows_the_report_scope(self):
        both = {"fixed_filters": {"legacy_source": ["車行", "網路平台"]}}
        self.assertEqual(display_dimension("legacy_dealer", both, {"fixed_filters": {"legacy_source": ["網路平台"]}}), "平台")
        self.assertEqual(display_dimension("legacy_dealer", {}, {"fixed_filters": {"legacy_source": ["車行"]}}), "車行")

    def test_other_dimensions_and_keys_are_unchanged(self):
        self.assertEqual(DIMENSIONS["legacy_dealer"], "原報表車行／平台名稱（比對用）")
        for key in ("month", "brand", "legacy_sales_source", "source", "recipient"):
            self.assertEqual(display_dimension(key, {"fixed_filters": {"legacy_source": ["車行"]}}), DIMENSIONS[key])
        self.assertEqual(display_dimension(None), "")


class DesignerDropdownTests(SimpleTestCase):
    def test_designer_shows_neutral_name_with_same_key(self):
        options = dict(choice for _, group in designer_dimension_choices() for choice in group)
        self.assertEqual(options["legacy_dealer"], "車行／平台")
        self.assertFalse(any(OLD in label for label in options.values()))
        # 其他維度名稱不變。
        self.assertEqual(options["legacy_sales_source"], "銷售來源")
        self.assertEqual(options["legacy_motor_type"], "車種類別（白牌、綠牌、速克達…）")


class DesignerFormTests(TestCase):
    def test_dimension_and_series_dropdowns(self):
        form = CardForm()
        for name in ("dimension", "series"):
            with self.subTest(field=name):
                options = {key: label for group in form.fields[name].choices if isinstance(group[1], list)
                           for key, label in group[1]}
                self.assertEqual(options["legacy_dealer"], "車行／平台")


class ReportPageDealerLabelTests(TestCase):
    PAGES = {"4": electric_platform_sales, "6": gasoline_platform_sales,
             "9": dealer_sales, "10": lambda: dealer_sales(gasoline=True),
             "11": dealer_counts, "12": lambda: dealer_counts(gasoline=True)}

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", "admin@example.invalid", "Test-Only-123")
        electric = VehicleModel.objects.create(brand="eReady", name="Fun", model_number="EV060L", energy_type="electric")
        gas = VehicleModel.objects.create(brand="SUZUKI", name="Saluto", model_number="UC125", energy_type="gas")
        dealer = SalesSource.objects.create(name="甲車行", source_type="dealer")
        platform = SalesSource.objects.create(name="MOMO", source_type="platform")
        for model in (electric, gas):
            for source_type, source in (("dealer", dealer), ("platform", platform)):
                color = VehicleColor.objects.create(vehicle_model=model, name=f"白{source_type}{model.pk}")
                SalesOrder.objects.create(source_type=source_type, source=source, order_date=date(2026, 10, 2),
                    registration_date=date(2026, 10, 3), registration_completed_at=timezone.now(),
                    owner_type="company", owner_name="合成車主", owner_id_number="83739807",
                    vehicle_model=model, color=color, vehicle_price=10000, actual_balance=10000,
                    calculated_balance=10000, payment_type="cash", status="completed")
        cls.reports = {}
        for key, build in cls.PAGES.items():
            config = {**build(), "audience": "team"}
            cls.reports[key] = ReportDefinition.objects.create(draft=config, published=config, version=1)
        neutral = {**dealer_sales(), "audience": "team", "reader_layout": "standard"}
        neutral["fixed_filters"] = {key: value for key, value in neutral["fixed_filters"].items() if key != "legacy_source"}
        cls.reports["neutral"] = ReportDefinition.objects.create(draft=neutral, published=neutral, version=1)

    def setUp(self):
        self.client.force_login(self.admin)

    def page(self, key):
        response = self.client.get(reverse("report_display", args=[self.reports[key].pk]))
        self.assertEqual(response.status_code, 200)
        return response

    def csv_header(self, key):
        response = self.client.get(reverse("report_export", args=[self.reports[key].pk, 0]), {"format": "csv"})
        self.assertEqual(response.status_code, 200)
        return response.content.decode("utf-8-sig").splitlines()[0]

    def test_platform_pages_say_platform(self):
        for key in ("4", "6"):
            with self.subTest(report=key):
                html = self.page(key).content.decode()
                self.assertIn('aria-label="平台圖例"', html)
                self.assertNotIn(OLD, html)
                self.assertEqual(self.csv_header(key), "月份,平台,訂單台數")

    def test_dealer_pages_say_dealer(self):
        for key in ("9", "10"):
            with self.subTest(report=key):
                response = self.page(key)
                html = response.content.decode()
                self.assertRegex(html, r"<small>車行 · 訂單台數</small>")
                self.assertIn("最多的車行", [tile["label"] for tile in response.context["kpis"]])
                self.assertNotIn(OLD, html)
                self.assertEqual(self.csv_header(key), "車行,月份,訂單台數")

    def test_count_pages_say_dealer_on_screen_and_in_csv(self):
        for key in ("11", "12"):
            with self.subTest(report=key):
                html = self.page(key).content.decode()
                head = re.search(r'<table class="report-results report-summary-table">.*?<thead>(.*?)</thead>', html, re.S).group(1)
                self.assertEqual(re.findall(r"<th[^>]*>([^<]*)</th>", head), ["車行", "訂單台數", "台數獎金", "傭金"])
                self.assertNotIn(OLD, html)
                self.assertEqual(self.csv_header(key), "車行,訂單台數,DMIS 已分配台數獎金,DMIS 車行傭金支出")

    def test_unrestricted_page_uses_neutral_name(self):
        response = self.page("neutral")
        html = response.content.decode()
        self.assertIn("<small>車行／平台 · 訂單台數</small>", html)
        self.assertIn("最多的車行／平台", [tile["label"] for tile in response.context["kpis"]])
        self.assertEqual(self.csv_header("neutral"), "車行／平台,月份,訂單台數")

    def test_csv_with_notes_and_records_export_keep_other_columns(self):
        response = self.client.get(reverse("report_export", args=[self.reports["9"].pk, 0]))
        lines = response.content.decode("utf-8-sig").splitlines()
        self.assertIn("車行,月份,訂單台數,訂單台數", lines)
        self.assertFalse(any(OLD in line for line in lines))
        records = self.client.get(reverse("report_records_export", args=[self.reports["9"].pk])).content.decode("utf-8-sig")
        self.assertIn("售出車行", records)
