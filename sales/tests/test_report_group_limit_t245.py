"""T-245：時間類分類不套用顯示群數（全部期數，上限 MAX_GROUPS）；分類圖 CSV 匯出完整清單，圖上維持前 N 群。"""
import csv
import io
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import ReportDefinition, SalesOrder, SalesSource, VehicleColor, VehicleModel
from sales.reporting.engine import card_result
from sales.reporting.views import initial_config

MONTHS = 30  # 超過走勢圖原本的 24 期
SOURCES = 5


def month_of(index):
    return date(2024 + index // 12, index % 12 + 1, 15)


class ReportGroupLimitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", "admin@example.invalid", "Test-Only-123")
        model = VehicleModel.objects.create(brand="SUZUKI", name="群數測試車", energy_type="gas")
        color = VehicleColor.objects.create(vehicle_model=model, name="白")
        cls.sources = [SalesSource.objects.create(name=f"車行{index}", source_type="dealer") for index in range(SOURCES)]
        for index in range(MONTHS):
            registered = month_of(index)
            SalesOrder.objects.create(source_type="dealer", source=cls.sources[index % SOURCES], order_date=registered,
                registration_date=registered, registration_completed_at=timezone.now(),
                owner_type="company", owner_name="合成車主", owner_id_number="83739807",
                vehicle_model=model, color=color, vehicle_price=10000, actual_balance=10000,
                calculated_balance=10000, payment_type="cash", status="completed")
        cls.config = {**initial_config(), "audience": "team"}

    def card(self, **changes):
        return {"title": "測試圖", "dimension": "month", "metric": "count", "chart": "line", "formula": "",
                "limit": 24, "sort": "key_desc", **changes}

    def report(self, card):
        config = {**self.config, "cards": [card]}
        return ReportDefinition.objects.create(draft=config, published=config, version=1)

    def export_rows(self, report, header):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("report_export", args=[report.pk, 0]))
        self.assertEqual(response.status_code, 200)
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
        start = next(index for index, row in enumerate(rows) if row and row[0] == header)
        notes = [row for row in rows[start + 1:] if row and row[0] == "提醒"]
        return [row for row in rows[start + 1:] if row and row[0] != "提醒"], notes

    # --- A：時間類分類顯示全部期數 ---

    def test_month_trend_over_24_periods_shows_all_periods(self):
        result = card_result(self.config, self.card(), {})
        self.assertEqual(len(result["rows"]), MONTHS)
        self.assertFalse(result["truncated"])
        self.assertEqual(result["truncation_note"], "")
        self.assertEqual(result["rows"][0]["label"], f"{month_of(MONTHS - 1):%Y/%m}")  # 排序照卡片設定：由近到遠
        self.assertEqual(result["rows"][-1]["label"], f"{month_of(0):%Y/%m}")

    def test_stacked_and_summary_table_month_show_all_periods(self):
        stacked = card_result(self.config, self.card(chart="stacked", series="source", series_limit=200,
                                                       series_other=False, series_sort="value"), {})
        self.assertEqual(len(stacked["rows"]), MONTHS)
        self.assertFalse(stacked["truncated"])
        table = card_result(self.config, self.card(chart="table", additional_metrics=["sale_total"]), {})
        self.assertTrue(table["summary_table"])
        self.assertEqual(len(table["rows"]), MONTHS)
        self.assertFalse(table["truncated"])

    def test_reader_grain_override_to_month_ignores_limit(self):
        card = self.card(dimension="year", limit=1)
        self.assertEqual(len(card_result(self.config, card, {})["rows"]), 3)
        self.assertEqual(len(card_result(self.config, card, {"_card_grain": "month"})["rows"]), MONTHS)

    def test_periods_over_max_groups_are_capped_with_coarser_grain_hint(self):
        with patch("sales.reporting.engine.MAX_GROUPS", 20):
            result = card_result(self.config, self.card(), {})
            table = card_result(self.config, self.card(chart="table", additional_metrics=["sale_total"]), {})
            day = card_result(self.config, self.card(), {"_card_grain": "day"})
        self.assertEqual(len(result["rows"]), 20)
        self.assertTrue(result["truncated"])
        self.assertIn("超過 20 期", result["truncation_note"])
        self.assertIn("改成按年", result["truncation_note"])
        self.assertEqual(len(table["rows"]), 20)
        self.assertIn("表格與 CSV 只含排序後的前 20 期", table["truncation_note"])
        self.assertIn("改成按月或按年", day["truncation_note"])

    def test_month_page_shows_all_periods_without_truncation_notice(self):
        report = self.report(self.card())
        self.client.force_login(self.admin)
        response = self.client.get(reverse("report_display", args=[report.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["results"][0]["rows"]), MONTHS)
        self.assertNotContains(response, "僅顯示前")
        self.assertNotContains(response, "圖表顯示前")
        rows, notes = self.export_rows(report, "月份")
        self.assertEqual(len(rows), MONTHS)
        self.assertEqual(notes, [])

    # --- B：分類圖圖上前 N 群、CSV 完整清單 ---

    def test_category_chart_keeps_top_n_and_csv_has_full_list(self):
        card = self.card(dimension="source", chart="bar", sort="value", limit=2)
        result = card_result(self.config, card, {})
        self.assertEqual(len(result["rows"]), 2)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["count"], MONTHS)  # 上方彙總仍是完整範圍
        self.assertEqual(result["truncation_note"], "圖表顯示前 2 群，CSV 含完整清單；上方彙總包含完整篩選範圍。")
        self.assertNotIn("其他", [row["label"] for row in result["rows"]])  # 不做「其他」合併
        report = self.report(card)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("report_display", args=[report.pk]))
        self.assertContains(response, "圖表顯示前 2 群，CSV 含完整清單")
        self.assertNotContains(response, "圖表與 CSV 不含其餘群組")
        rows, notes = self.export_rows(report, result["dimension_label"])
        self.assertEqual(sorted(row[0] for row in rows), sorted(source.name for source in self.sources))
        self.assertEqual(notes, [])

    def test_category_summary_table_csv_has_full_list(self):
        card = self.card(dimension="source", chart="table", sort="value", limit=2, additional_metrics=["sale_total"])
        result = card_result(self.config, card, {})
        self.assertEqual(len(result["rows"]), 2)
        self.assertIn("表格顯示前 2 群，CSV 含完整清單", result["truncation_note"])
        rows, notes = self.export_rows(self.report(card), result["table_dimension_labels"][0])
        self.assertEqual(len(rows), SOURCES)
        self.assertEqual(notes, [])

    def test_category_stacked_csv_has_full_list(self):
        card = self.card(dimension="source", chart="stacked", sort="value", limit=2, series="brand",
                         series_limit=200, series_other=False, series_sort="value")
        result = card_result(self.config, card, {})
        self.assertEqual(len(result["rows"]), 2)
        rows, notes = self.export_rows(self.report(card), result["dimension_label"])
        self.assertEqual(len({row[0] for row in rows}), SOURCES)
        self.assertEqual(notes, [])

    def test_category_csv_over_max_groups_says_so(self):
        card = self.card(dimension="source", chart="bar", sort="value", limit=2)
        report = self.report(card)
        with patch("sales.reporting.engine.MAX_GROUPS", 3):
            result = card_result(self.config, card, {})
            rows, notes = self.export_rows(report, result["dimension_label"])
        self.assertEqual(len(result["rows"]), 2)
        self.assertIn("CSV 含完整清單（上限 3 群，其餘未匯出）", result["truncation_note"])
        self.assertEqual(len(rows), 3)
        self.assertEqual(notes, [["提醒", "僅匯出前 3 群，非全部群組"]])

    def test_category_within_limit_has_no_notice(self):
        result = card_result(self.config, self.card(dimension="source", chart="bar", sort="value", limit=SOURCES), {})
        self.assertEqual(len(result["rows"]), SOURCES)
        self.assertFalse(result["truncated"])
        self.assertEqual(result["truncation_note"], "")
