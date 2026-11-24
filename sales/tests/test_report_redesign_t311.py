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


class HeatTableAssetsTests(SimpleTestCase):
    def test_dealer_and_platform_use_heat_table_with_validated_scale(self):
        heat = (ROOT / "static/js/report-heat.js").read_text(encoding="utf-8")
        self.assertIn("const REPORT_HEAT_LEVELS = 5;", heat)
        self.assertIn("其他平台", heat)
        interactions = (ROOT / "static/js/report-interactions.js").read_text(encoding="utf-8")
        self.assertIn("['dealer_overview', 'platform_overview'].includes(layout)", interactions)
        css = (ROOT / "static/css/app.css").read_text(encoding="utf-8")
        for color in ("#a3acf9", "#7d8af6", "#5767f3", "#3446f0", "#1f2aa6", "#3b48ad", "#5262e6", "#7581ff", "#9ea6ff", "#c9cdff"):
            self.assertIn(color, css)
        self.assertEqual(len(re.findall(r"--heat-5: #", css)), 3)  # 亮色、night-blue、跟隨系統深色
        for page in ("layout.html", "designer_frame.html"):
            html = (ROOT / "templates/sales/reporting" / page).read_text(encoding="utf-8")
            self.assertLess(html.index("js/report-heat.js"), html.index("js/report-interactions.js"))


class CountExpandTests(TestCase):
    """台數統計（#13 #14）：點車行就地展開訂單，用同一個 report_detail 與 group，只多 view=count。"""
    @classmethod
    def setUpTestData(cls):
        from sales.tests import test_reporting as fixtures
        fixtures.ReportingTests.setUpTestData.__func__(cls)

    def setUp(self):
        from sales.reporting.engine import validate_config
        from sales.reporting.source_templates import SOURCE_TEMPLATES
        from sales.tests import test_reporting as fixtures
        self.report.published = validate_config(SOURCE_TEMPLATES["gasoline-count"]())
        self.report.save()
        fixtures.ReportingTests.login(self)

    def test_page_folds_full_records_and_loads_expand_script(self):
        html = self.client.get(reverse("report_display", args=[self.report.pk])).content.decode()
        self.assertIn("data-records-fold", html)
        self.assertNotIn("data-records-fold open", html)
        self.assertIn("js/report-count.js", html)
        opened = self.client.get(reverse("report_display", args=[self.report.pk]), {"records_page": "1"}).content.decode()
        self.assertIn("data-records-fold open", opened)

    def test_count_view_lists_orders_with_short_columns(self):
        from sales.reporting.views import publication_key
        url = reverse("report_detail", args=[self.report.pk, 0])
        base = {"group": "__all__", "inline": "1", "revision": publication_key(self.report)}
        html = self.client.get(url, {**base, "view": "count", "label": "不存在的車行"}).content.decode()
        self.assertIn("data-count-orders", html)
        self.assertIn("領牌日期 · 車主", html)
        self.assertIn("歸屬：", html)  # 歸屬車行和展開的車行不同時才標
        plain = self.client.get(url, base).content.decode()
        self.assertNotIn("data-count-orders", plain)  # 沒有 view=count 照舊

    def test_count_view_only_for_count_layout(self):
        from sales.reporting.source_templates import SOURCE_TEMPLATES
        from sales.reporting.views import publication_key
        self.report.published = SOURCE_TEMPLATES["gasoline"]()
        self.report.save()
        url = reverse("report_detail", args=[self.report.pk, 0])
        html = self.client.get(url, {"group": "__all__", "inline": "1", "view": "count", "revision": publication_key(self.report)}).content.decode()
        self.assertNotIn("data-count-orders", html)

    def test_money_format(self):
        from sales.reporting.views import _count_money
        self.assertEqual(_count_money("0.00"), "")
        self.assertEqual(_count_money("1500.00"), "1,500")
        self.assertEqual(_count_money("12.50"), "12.50")
        self.assertEqual(_count_money("待補收支資料"), "待補收支資料")


class AnalysisViewsTests(SimpleTestCase):
    def test_car_paint_filter_uses_existing_color_families(self):
        from sales.templatetags.report_tags import car_paint, car_paint_outline
        self.assertEqual(car_paint("珍珠白 W1"), "#f4f5f7")
        self.assertTrue(car_paint_outline(car_paint("珍珠白")))
        self.assertEqual(car_paint("消光黑"), "#2b2d31")
        self.assertFalse(car_paint_outline(car_paint("消光黑")))
        self.assertEqual(car_paint("未知色"), "")

    def test_assets_and_rules(self):
        views = (ROOT / "static/js/report-analysis-views.js").read_text(encoding="utf-8")
        self.assertIn("const REPORT_SEX_ORDER = ['女性', '男性'];", views)
        self.assertIn("chart.dataset.series === 'sex'", views)
        self.assertIn("chart.dataset.dimension === 'family_color' && chart.dataset.series === 'age_group'", views)
        pie = (ROOT / "static/js/report-pie.js").read_text(encoding="utf-8")
        self.assertIn("fixed: chart.dataset.dimension === 'sex' ? ['女性', '男性'] : []", pie)
        for page in ("layout.html", "designer_frame.html"):
            html = (ROOT / "templates/sales/reporting" / page).read_text(encoding="utf-8")
            self.assertLess(html.index("js/report-analysis-views.js"), html.index("js/report-interactions.js"))


class AnalysisPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        MonthSwitchPageTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.client.force_login(self.admin)

    def test_scope_labels_fold_and_owner_list_collapsed(self):
        from sales.reporting.source_templates import sex_model_color_analysis
        report = ReportDefinition.objects.create(draft=sex_model_color_analysis(), published=sex_model_color_analysis(), version=1)
        html = self.client.get(reverse("report_display", args=[report.pk])).content.decode()
        self.assertIn('<details class="report-scope-fold"><summary>此圖固定條件</summary>', html)
        self.assertIn("data-records-fold", html)
        self.assertIn("車主名單（", html)

    def test_color_bars_carry_car_paint(self):
        report = ReportDefinition.objects.create(draft=model_analysis("color"), published=model_analysis("color"), version=1)
        html = self.client.get(reverse("report_display", args=[report.pk])).content.decode()
        self.assertIn('data-car-paint="#f4f5f7" data-car-paint-outline', html)
