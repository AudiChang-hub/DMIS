"""T-311 報表中心改版：月份圖切換（#4 #5 #7）與閱讀版型的圓餅（圖例一列一項、扇區百分比、前 5 名＋其他）。"""
import re
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import ReportDefinition, SalesOrder, VehicleColor, VehicleModel
from sales.reporting.reader_layouts import reader_cards
from sales.reporting.source_templates import electric_vehicle_sales, model_analysis, total_vehicle_sales

ROOT = Path(settings.BASE_DIR)


def result(index, chart, dimension, series="", date_dimension=False, series_label=""):
    return {"index": index, "card": {"chart": chart, "dimension": dimension, "series": series},
            "date_dimension": date_dimension, "series_label": series_label}


class ReaderCardsTests(SimpleTestCase):
    def items(self):
        return [result(0, "stacked", "month", "legacy_sales_source", True, "銷售來源"), result(1, "donut", "legacy_sales_source"),
                result(2, "stacked", "month", "legacy_motor_type", True, "舊報表車種分類（比對用）"), result(3, "donut", "legacy_motor_type")]

    def test_sales_layouts_merge_month_stacks_at_first_position(self):
        items = self.items()
        for layout in ("sales_overview", "electric_overview", "gasoline_overview"):
            cards = reader_cards({"reader_layout": layout}, items)
            self.assertEqual(len(cards), 3)
            self.assertEqual([member["result"]["index"] for member in cards[0]["switch"]], [0, 2])
            self.assertEqual([member["label"] for member in cards[0]["switch"]], ["依銷售來源", "依車種分類"])
            self.assertEqual([card["index"] for card in cards[1:]], [1, 3])

    def test_other_layouts_and_single_month_chart_stay_as_they_are(self):
        items = self.items()
        for layout in ("standard", "platform_overview", "dealer_overview", "count_overview", "analysis_overview", None):
            self.assertEqual(reader_cards({"reader_layout": layout} if layout else {}, items), items)
        single = [items[0], items[1]]
        self.assertEqual(reader_cards({"reader_layout": "sales_overview"}, single), single)


class ReaderPieAssetsTests(SimpleTestCase):
    def test_pie_rules_and_scripts(self):
        pie = (ROOT / "static/js/report-pie.js").read_text(encoding="utf-8")
        self.assertIn("const REPORT_PIE_MAX = 6;", pie)       # 超過 6 項才合併，畫前 5 名＋其他
        self.assertIn("const REPORT_PIE_INSIDE = 7;", pie)    # ≥ 7% 標在環上
        self.assertIn("其餘 ${merged.length} 項", pie)        # 資料本身有「其他」時改名
        self.assertIn("原報表未列出的", pie)
        interactions = (ROOT / "static/js/report-interactions.js").read_text(encoding="utf-8")
        # 只有閱讀版型的圓餅換新畫法；一般報表照舊。
        self.assertIn('chart.dataset.chart === "donut" && overview && typeof renderReportPie === "function"', interactions)
        layout = (ROOT / "templates/sales/reporting/layout.html").read_text(encoding="utf-8")
        frame = (ROOT / "templates/sales/reporting/designer_frame.html").read_text(encoding="utf-8")
        for page in (layout, frame):
            self.assertLess(page.index("js/report-pie.js"), page.index("js/report-interactions.js"))
            self.assertLess(page.index("js/report-month-switch.js"), page.index("js/report-interactions.js"))

    def test_legend_names_do_not_wrap_per_character(self):
        css = (ROOT / "static/css/report-overview.css").read_text(encoding="utf-8")
        legend = re.search(r"\.report-pie-legend \.report-overview-legend__name \{([^}]*)\}", css).group(1)
        self.assertIn("white-space:nowrap", legend)
        self.assertIn("text-overflow:ellipsis", legend)
        self.assertIn("@container (min-width: 480px)", css)
        self.assertRegex(css, r"@media \(prefers-reduced-motion: reduce\) \{\s*\.report-chart-switch__tabs \[role=tab\] \{ transition:none; \}")


class MonthSwitchPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", "admin@example.invalid", "Test-Only-123")
        model = VehicleModel.objects.create(brand="eReady", name="Fun", model_number="EV060L", energy_type="electric")
        color = VehicleColor.objects.create(vehicle_model=model, name="白")
        for day in (3, 4):
            SalesOrder.objects.create(source_type="store", order_date=date(2026, 10, 2), registration_date=date(2026, 10, day),
                                      registration_completed_at=timezone.now(), owner_type="local", owner_name="合成車主",
                                      owner_id_number="A123456789", vehicle_model=model, color=color, vehicle_price=10000,
                                      actual_balance=10000, calculated_balance=10000, payment_type="cash", status="completed")

    def setUp(self):
        self.client.force_login(self.admin)

    def page(self, config):
        report = ReportDefinition.objects.create(draft=config, published=config, version=1)
        return self.client.get(reverse("report_display", args=[report.pk])).content.decode()

    def test_electric_page_has_one_switch_with_model_first_and_two_pies(self):
        html = self.page(electric_vehicle_sales())
        self.assertEqual(html.count("data-chart-switch"), 1)
        tabs = re.findall(r'data-switch-tab="(\d+)">([^<]+)</button>', html)
        self.assertEqual(tabs, [("0", "依型號"), ("1", "依銷售來源")])
        self.assertEqual(html.count("data-switch-panel"), 2)
        self.assertIn('aria-labelledby="chart-switch-tab-0"', html)
        self.assertEqual(html.count('data-chart="donut"'), 2)
        self.assertIn("data-current-month=", html)
        # 圖卡順序：切換卡、型號圓餅、銷售來源圓餅
        self.assertLess(html.index("data-chart-switch"), html.index('id="chart-2"'))
        self.assertLess(html.index('id="chart-2"'), html.index('id="chart-3"'))

    def test_total_sales_switch_without_config_change(self):
        html = self.page(total_vehicle_sales())
        self.assertEqual(re.findall(r'data-switch-tab="(\d+)">([^<]+)</button>', html), [("0", "依銷售來源"), ("2", "依車種分類")])

    def test_analysis_page_has_no_switch(self):
        html = self.page(model_analysis("sex"))
        self.assertNotIn("data-chart-switch", html)
        self.assertNotIn("data-switch-panel", html)
