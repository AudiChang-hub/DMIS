"""T-182（使用者 2026-11-16 選 B）：報表頁 KPI 摘要、圖表配色參數、卡片底部總數與手機不左右捲動。"""
import re
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import ReportDefinition, SalesOrder, VehicleColor, VehicleModel
from sales.reporting.engine import OTHER_COLOR, dimension_color
from sales.reporting.kpis import reader_kpis
from sales.reporting.views import initial_config


ROOT = Path(settings.BASE_DIR)


def card(chart, dimension, **extra):
    return {"chart": chart, "dimension": dimension, "metric": "count", "fixed_filters": {}, **extra}


def row(label, value, percentage=None):
    return {"label": label, "value": str(value), "display": f"{value:,}", "percentage": percentage}


class ReaderKpiTests(SimpleTestCase):
    def test_count_donut_shares_and_peak_month_come_from_existing_results(self):
        results = [
            {"card": card("stacked", "month"), "count": 1814, "rows": [row("2026/02", 104), row("2026/03", 196), row("未領牌", 300)]},
            {"card": card("donut", "legacy_sales_source"), "count": 1814,
             "rows": [row("馭盛", 518, 28.6), row("車行", 687, 37.9), row("展場", 88, 4.9)]},
        ]
        tiles = reader_kpis(results)
        self.assertEqual([tile["label"] for tile in tiles], ["訂單", "車行", "馭盛", "單月最高"])
        self.assertEqual(tiles[0]["value"], "1,814")
        self.assertEqual((tiles[1]["value"], tiles[1]["unit"], tiles[1]["color"]), ("37.9", "%", "var(--chart-s1)"))
        # 單月最高只比有日期的月份，「未領牌」不算一個月。
        self.assertEqual((tiles[3]["value"], tiles[3]["sub"]), ("196", "2026/03"))

    def test_largest_category_skips_neutral_groups(self):
        results = [{"card": card("stacked", "age_group"), "count": 667, "dimension_label": "年齡層（生日未填獨立列示）",
                    "rows": [row("公司或其他", 900, 50.0), row("40-49歲", 199, 29.8), row("30-39歲", 165, 24.7)]}]
        tiles = reader_kpis(results)
        self.assertEqual(tiles[1]["label"], "最多的年齡層")
        self.assertEqual(tiles[1]["value"], "40-49歲")

    def test_summary_table_lists_group_count_and_money_totals(self):
        results = [{"card": card("table", "legacy_dealer", additional_metrics=["dealer_bonus", "dealer_commission"]),
                    "count": 186, "rows": [row("A", 42), row("B", 35)], "summary_table": True,
                    "table_header_labels": ["車行", "訂單台數", "台數獎金", "傭金"], "table_dimension_labels": ["車行"],
                    "table_total_cells": [{"display": "186"}, {"display": "40,500"}, {"display": "93,000"}]}]
        tiles = reader_kpis(results)
        self.assertEqual([(tile["label"], tile["value"], tile["unit"]) for tile in tiles],
                         [("訂單", "186", "張"), ("車行數", "2", ""), ("台數獎金", "40,500", "元"), ("傭金", "93,000", "元")])

    def test_cards_with_their_own_scope_are_not_summarised(self):
        per_model = [{"card": card("donut", "sex", fixed_filters={"model_exact": ["EV076SZV"]}), "count": 80, "rows": [row("男性", 40, 50.0)]}]
        self.assertEqual(reader_kpis(per_model), [])

    def test_selection_uses_the_card_that_applied_the_cross_filter(self):
        results = [
            {"card": card("stacked", "age_group"), "count": 667, "retained_candidates": True, "rows": [row("30-39歲", 165, 24.7)]},
            {"card": card("donut", "sex"), "count": 165, "rows": [row("男性", 90, 54.5), row("女性", 75, 45.5)]},
        ]
        self.assertEqual(reader_kpis(results)[0]["value"], "165")


class PaletteTests(SimpleTestCase):
    def test_same_category_keeps_the_same_token_on_every_page(self):
        self.assertEqual(dimension_color("legacy_sales_source", "車行", 4), "var(--chart-s1)")
        self.assertEqual(dimension_color("sex", "女性", 0), "var(--chart-s2)")
        self.assertEqual(dimension_color("sex", "公司或其他", 0), OTHER_COLOR)
        self.assertEqual(dimension_color("brand", "SUZUKI", 9), "var(--chart-s2)")

    def test_chart_tokens_exist_for_light_and_both_dark_scopes(self):
        css = (ROOT / "static/css/app.css").read_text(encoding="utf-8")
        tokens = [f"--chart-s{index}" for index in range(1, 9)] + ["--chart-other"]
        for token in tokens:
            self.assertEqual(len(re.findall(rf"^\s*{re.escape(token)}:\s*#[0-9a-f]{{6}};", css, re.M)), 3, token)

    def test_old_overrides_that_forced_scrolling_and_flat_type_are_gone(self):
        css = (ROOT / "static/css/reporting.css").read_text(encoding="utf-8") + (ROOT / "static/css/report-overview.css").read_text(encoding="utf-8")
        self.assertNotIn("font-size:var(--text-base) !important", css)
        self.assertNotRegex(css, r"report-(overview|analysis)-plot\s*\{[^}]*min-width:\s*(520|640)px")
        js = (ROOT / "static/js/report-interactions.js").read_text(encoding="utf-8") + (ROOT / "static/js/report-analysis.js").read_text(encoding="utf-8")
        for legacy in ("#737373", "#7ac36a", "#f15a60"):
            self.assertNotIn(legacy, js)


class ReaderPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", "admin@example.invalid", "Test-Only-123")
        model = VehicleModel.objects.create(brand="eReady", name="Fun", model_number="EV060L", energy_type="electric")
        color = VehicleColor.objects.create(vehicle_model=model, name="白")
        for index, id_number in enumerate(("A123456789", "A223456789", "83739807")):
            SalesOrder.objects.create(source_type="store", order_date=date(2026, 10, 2), registration_date=date(2026, 10, 3 + index), registration_completed_at=timezone.now(),
                owner_type="company" if id_number.isdigit() else "local", owner_name="合成車主", owner_id_number=id_number,
                vehicle_model=model, color=color, vehicle_price=10000, actual_balance=10000, calculated_balance=10000,
                payment_type="cash", status="completed")
        config = {**initial_config(), "audience": "team"}
        cls.report = ReportDefinition.objects.create(draft=config, published=config, version=1)

    def setUp(self):
        self.client.force_login(self.admin)

    def test_page_has_kpi_strip_and_card_footer(self):
        html = self.client.get(reverse("report_display", args=[self.report.pk])).content.decode()
        strip = html[html.index("data-report-kpis"):]
        strip = strip[:strip.index("</section>")]
        self.assertIn('class="report-kpi__label">訂單</dt>', strip)
        self.assertIn("<strong>3</strong>", strip)
        # KPI 在篩選之後、圖卡之前；原地更新時與圖卡一起換新。
        self.assertLess(html.index('class="report-panel report-filter"'), html.index("data-report-kpis"))
        self.assertLess(html.index("data-report-kpis"), html.index('class="report-grid"'))
        self.assertIn('"[data-report-kpis]"', (ROOT / "static/js/report-interactions.js").read_text(encoding="utf-8"))
        footer = re.search(r'<footer class="report-card-foot">.*?</footer>', html, re.S).group(0)
        self.assertIn("共 3 張訂單", footer)
        self.assertIn("data-report-open-detail", footer)
