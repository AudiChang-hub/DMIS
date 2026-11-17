"""T-212：報表中心的領牌年月改成「年 → 月」樹狀；送出仍是月份清單，網址參數與後端篩選不變。"""
import re
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import ReportDefinition, SalesOrder, SalesSource, VehicleColor, VehicleModel
from sales.reporting.forms import FilterForm
from sales.reporting.views import initial_config


class ReportMonthTreeTests(TestCase):
    MONTHS = (date(2025, 11, 3), date(2025, 12, 3), date(2026, 1, 5), date(2026, 2, 5), date(2026, 2, 20))

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("t212-admin", "t212@example.invalid", "Test-Only-123")
        source = SalesSource.objects.create(name="年月樹車行", source_type="dealer")
        model = VehicleModel.objects.create(brand="SUZUKI", name="年月樹測試車", energy_type="gas")
        color = VehicleColor.objects.create(vehicle_model=model, name="白")
        for day in cls.MONTHS:
            SalesOrder.objects.create(source_type="dealer", source=source, order_date=day, registration_date=day,
                registration_completed_at=timezone.now(), owner_type="company", owner_name="合成車主",
                owner_id_number="83739807", vehicle_model=model, color=color, vehicle_price=10000,
                actual_balance=10000, calculated_balance=10000, payment_type="cash", status="completed")
        cls.config = {**initial_config(), "audience": "team", "include_records": True}
        cls.report = ReportDefinition.objects.create(draft=cls.config, published=cls.config, version=1)
        overview = {**cls.config, "reader_layout": "sales_overview"}
        cls.overview = ReportDefinition.objects.create(draft=overview, published=overview, version=1)

    def setUp(self):
        self.client.force_login(self.admin)

    def page(self, report, params=None):
        return self.client.get(reverse("report_display", args=[report.pk]), params or {})

    @staticmethod
    def tree(html):
        return re.search(r'<div class="report-month-tree" data-month-tree>.*?</div><script', html, re.S).group(0)

    def test_months_render_as_year_tree_newest_first_and_collapsed(self):
        html = self.page(self.report).content.decode()
        tree = self.tree(html)
        self.assertEqual(re.findall(r'data-month-year="(\d{4})"', tree), ["2026", "2025"])
        self.assertEqual(tree.count('role="checkbox"'), 2)
        self.assertEqual(tree.count('aria-expanded="false"'), 2)
        self.assertEqual(tree.count('role="group"'), 2)
        self.assertEqual(len(re.findall(r'role="group" aria-label="\d{4} 年各月" hidden>', tree)), 2, "預設收合")
        # 月份仍是原本的 months 勾選框，值與順序同下拉原本的選項（新到舊）。
        self.assertEqual(re.findall(r'name="months" value="([\d-]+)"', tree), ["2026-02", "2026-01", "2025-12", "2025-11"])
        self.assertIn('<span class="sr-only">2026 年 </span>02 月', tree)
        self.assertIn("js/report-month-tree.js", html)

    def test_year_state_is_checked_mixed_or_unchecked(self):
        tree = self.tree(self.page(self.report, {"months": ["2026-02", "2026-01", "2025-12"]}).content.decode())
        self.assertRegex(tree, r'(?s)data-month-year="2026">.*?aria-checked="true".*?2／2')
        self.assertRegex(tree, r'(?s)data-month-year="2025">.*?aria-checked="mixed".*?1／2')
        tree = self.tree(self.page(self.report).content.decode())
        self.assertEqual(tree.count('aria-checked="false"'), 2)

    def test_submitted_parameters_and_filtering_are_unchanged(self):
        months = ["2026-02", "2026-01"]
        form = FilterForm({"months": months}, config=self.config)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["months"], months)
        self.assertNotIn("year", form.fields)
        response = self.page(self.report, {"months": months})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["filter_form"].cleaned_data["months"], months)
        self.assertEqual(response.context["records_page"].paginator.count, 3)  # 2026/01、2026/02 共 3 張
        everything = self.page(self.report)
        self.assertEqual(everything.context["records_page"].paginator.count, 5)

    def test_chip_shows_whole_year_or_each_month(self):
        def chip(params, report=None):
            response = self.page(report or self.report, params)
            return {item["label"]: item for item in response.context["active_filters"]}
        whole = chip({"months": ["2026-02", "2026-01"]})["月份"]
        self.assertEqual(whole["value"], "2026 全年")
        self.assertEqual(whole["title"], "2026 全年")
        self.assertEqual(chip({"months": ["2026-02", "2025-12"]})["月份"]["value"], "2026/02、2025/12")
        self.assertEqual(chip({"months": ["2026-02", "2026-01", "2025-12"]})["月份"]["value"], "2026 全年、2025/12")
        self.assertEqual(chip({"months": ["2026-02", "2026-01", "2025-12", "2025-11"]})["月份"]["value"], "2026 全年、2025 全年")
        self.assertEqual(chip({"months": ["2026-02", "2026-01"]}, self.overview)["領牌年月"]["value"], "2026 全年")

    def test_overview_keeps_source_style_controls(self):
        html = self.page(self.overview).content.decode()
        self.assertIn("data-month-tree-control", html)
        tree = self.tree(html)
        self.assertEqual(re.findall(r'name="months" value="([\d-]+)"', tree), ["2026-02", "2026-01", "2025-12", "2025-11"])
        self.assertIn('name="empty_months"', html)
