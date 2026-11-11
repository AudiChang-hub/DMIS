"""T-143：台數統計頁表頭改短欄名、台數表與來源明細改上下全寬；CSV 欄名與其他報表不變。"""
import re

from django.test import TestCase
from django.urls import reverse

from sales.reporting.engine import validate_config
from sales.reporting.source_templates import SOURCE_TEMPLATES
from sales.tests import test_reporting as fixtures
from sales.tests.test_report_link_affordance_t141 import css_rules, declarations

LONG = ["原報表車行／平台名稱（比對用）", "DMIS 已分配台數獎金", "DMIS 車行傭金支出"]
MAIN = '.report-reader-main[data-reader-layout="count_overview"]'


def thead(html, table_class):
    match = re.search(r'<table class="report-results ' + table_class + r'">.*?<thead>(.*?)</thead>', html, re.S)
    return re.sub(r"<[^>]+>", "|", match.group(1))


class CountOverviewHeaderTests(TestCase):
    login = fixtures.ReportingTests.login

    @classmethod
    def setUpTestData(cls):
        fixtures.ReportingTests.setUpTestData.__func__(cls)

    def publish(self, key):
        self.report.published = validate_config(SOURCE_TEMPLATES[key]())
        self.report.save()
        self.login()

    def test_both_count_pages_show_short_headers_in_summary_and_record_tables(self):
        for key in ("gasoline-count", "electric-count"):
            with self.subTest(key=key):
                self.publish(key)
                html = self.client.get(reverse("report_display", args=[self.report.pk])).content.decode()
                summary = thead(html, "report-summary-table")
                self.assertEqual([cell for cell in summary.split("|") if cell.strip()], ["車行", "訂單台數", "台數獎金", "傭金"])
                records = thead(html, "report-detail-table")
                self.assertIn("台數獎金", records)
                self.assertIn("傭金", records)
                self.assertIn("售出車行", records)
                # 手機卡片用 data-label 當欄名，也要是短欄名（測試資料只有油車訂單有明細列）。
                if key == "gasoline-count":
                    self.assertIn('data-label="台數獎金"', html)
                    self.assertIn('data-label="傭金"', html)
                for label in LONG:
                    self.assertNotIn(label, summary)
                    self.assertNotIn(label, records)
                    self.assertNotIn(f'data-label="{label}"', html)

    def test_csv_exports_keep_original_column_names(self):
        self.publish("gasoline-count")
        chart = self.client.get(reverse("report_export", args=[self.report.pk, 0])).content.decode("utf-8-sig")
        self.assertIn(",".join(["原報表車行／平台名稱（比對用）", "訂單台數", "DMIS 已分配台數獎金", "DMIS 車行傭金支出"]), chart)
        records = self.client.get(reverse("report_records_export", args=[self.report.pk])).content.decode("utf-8-sig")
        self.assertIn("售出車行", records)
        self.assertIn("DMIS 已分配台數獎金,DMIS 車行傭金支出", records)

    def test_other_reports_keep_original_headers(self):
        config = SOURCE_TEMPLATES["gasoline-count"]()
        config["reader_layout"] = "dealer_overview"
        self.report.published = validate_config(config)
        self.report.save()
        self.login()
        html = self.client.get(reverse("report_display", args=[self.report.pk])).content.decode()
        summary = thead(html, "report-summary-table")
        for label in LONG:
            self.assertIn(label, summary)
        self.assertIn("DMIS 車行傭金支出", thead(html, "report-detail-table"))


class CountOverviewStackedLayoutTests(TestCase):
    def test_count_page_stacks_summary_above_records_at_full_width(self):
        rules = css_rules("report-overview.css")
        main = declarations(rules, MAIN)
        self.assertIn("display:block", main[0].replace(" ", ""))
        self.assertFalse([body for found, body in rules if MAIN in found and "grid-template-columns" in body
                          and ".report-grid" not in found])
        self.assertFalse([body for found, body in rules if MAIN in found and "grid-column:2" in body.replace(" ", "")])
        # 不再用固定最小寬度撐開表格；手機卡片模式（≤800px）才不會被推出畫面外。
        self.assertFalse([body for found, body in rules if MAIN in found and re.search(r"min-width:\s*\d{3}px", body)])
        self.assertIn("min-width:0", declarations(rules, MAIN + " .report-record-panel td")[0].replace(" ", ""))
        self.assertIn("text-align:right", declarations(rules, MAIN + " .report-summary-table thead th:not(:first-child)")[0])
        # 其他版型的規則沒有被一起移除。
        self.assertTrue(declarations(rules, '.report-reader-main[data-reader-layout="gasoline_overview"] .report-grid > .report-chart:first-child'))
