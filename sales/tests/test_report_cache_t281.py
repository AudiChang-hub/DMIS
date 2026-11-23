"""T-281 g：報表中心卡片快取（使用者 2026-11-21 選 A）與同頁共用查詢。

鎖住：
- 有快取與沒有快取的結果、畫面完全相同（每一種預設報表）。
- 資料沒變時第三次起直接讀快取，不再跑卡片查詢。
- 任何會影響分類或數字的資料一改就重算：存檔、QuerySet.update()（不更新 updated_at、不發訊號）、新增、刪除、
  分類規則發布、車型／車行／車色主檔、匯入列 JSON；卡片讀到的每張表都在資料版本內。
- 版號、日期、篩選條件不同就不共用；設計器預覽不走快取；快取服務故障時照常計算。
- 同一頁範圍相同的卡片，合計 COUNT／SUM 只查一次。
"""
import re
from datetime import date, timedelta
from unittest import mock

from django.apps import apps
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from sales.models import (
    LegacyImportBatch, LegacyImportRow, LegacySalesSnapshot, ReportClassification, ReportDefinition, SalesOrder, SalesSource,
    VehicleColor, VehicleModel,
)
from sales.reporting import cache as report_cache
from sales.reporting import views as report_views
from sales.reporting.classification import apply_change, impact, preview_token
from sales.reporting.engine import validate_config
from sales.reporting.source_templates import ALL_TEMPLATES
from sales.tests import test_reporting as fixtures

NO_CACHE = override_settings(REPORT_CARD_CACHE_SECONDS=0)
VOLATILE = re.compile(r'name="csrfmiddlewaretoken" value="[^"]+"|\d{1,2}:\d{2}:\d{2}')  # 查詢時間每秒不同


class ReportCardCacheTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.ReportingTests.setUpTestData.__func__(cls)
        batch = LegacyImportBatch.objects.create(import_type="operations", source_file="t281.xlsx", original_filename="t281.xlsx",
                                                 file_sha256="d" * 64, file_size=0, uploaded_by="tester")
        for index, (order, number) in enumerate(zip(SalesOrder.objects.order_by("pk"), ["UQ125DA", "DS250M4", "EV060L"])):
            row = LegacyImportRow.objects.create(batch=batch, sheet_name="銷售", source_row=index + 1, fingerprint=(f"t281{index}" * 13)[:64],
                                                 action="create", mapped_data={"model_number": number})
            LegacySalesSnapshot.objects.create(order=order, import_row=row)
        cls.templates = {}
        for name, factory in ALL_TEMPLATES.items():
            config = validate_config(factory())
            cls.templates[name] = ReportDefinition.objects.create(draft=config, published=config, version=1)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.admin)

    def page(self, report, params=None):
        response = self.client.get(reverse("report_display", args=[report.pk]), params or {})
        self.assertEqual(response.status_code, 200)
        return response

    def fresh(self, report, params=None):
        with NO_CACHE:
            return self.page(report, params)

    def warm(self, report, params=None):
        """第一次記下讀哪些表、第二次存結果、第三次命中。"""
        for _ in range(2):
            self.page(report, params)
        with mock.patch.object(report_views, "_results", wraps=report_views._results) as computed:
            response = self.page(report, params)
        self.assertEqual(computed.call_count, 0, "資料沒變時第三次應直接讀快取")
        return response

    def assert_current(self, report, params=None):
        expected = self.fresh(report, params).context["results"]
        actual = self.page(report, params).context["results"]
        self.assertEqual(actual, expected)
        return actual

    @staticmethod
    def numbers(results):
        return [[(row["label"], row["count"], [(s["label"], s["count"]) for s in row.get("segments", [])]) for row in item["rows"]]
                for item in results]

    def test_cached_pages_match_uncached_for_every_template(self):
        for name, report in [("initial", self.report), *self.templates.items()]:
            with self.subTest(report=name):
                expected = self.fresh(report)
                cached = self.warm(report)
                self.assertEqual(cached.context["results"], expected.context["results"])
                self.assertEqual(VOLATILE.sub("", cached.content.decode()), VOLATILE.sub("", expected.content.decode()))

    def test_hit_skips_card_queries(self):
        report = self.templates["total"]

        def card_sql():
            with CaptureQueriesContext(connection) as captured:
                self.page(report)
            return [q["sql"] for q in captured.captured_queries if "GROUP BY" in q["sql"]]
        self.assertTrue(card_sql())
        self.warm(report)
        self.assertEqual(card_sql(), [])

    def test_every_table_the_cards_read_is_in_the_data_version(self):
        report = self.templates["total"]
        with mock.patch.object(report_cache, "_set", wraps=report_cache._set) as stored:
            self.page(report)
        dependencies = next(args[1] for args, _ in stored.call_args_list if args[0].startswith("report-cards:deps:"))
        for table in ("sales_salesorder", "sales_legacyimportrow", "sales_legacysalessnapshot", "sales_vehiclemodel",
                      "sales_salessource", "sales_reportclassification"):
            self.assertIn(table, dependencies)
        models = {model._meta.db_table: model for model in apps.get_models(include_auto_created=True)}
        for table in dependencies:
            with self.subTest(table=table):
                model = models[table]
                row = model._base_manager.order_by("pk").first()
                if row is None:
                    continue
                before = report_cache.data_version(dependencies)
                field = next(f for f in model._meta.concrete_fields if f.name == "updated_at")
                model._base_manager.filter(pk=row.pk).update(**{field.name: timezone.now() + timedelta(days=3)})
                self.assertNotEqual(report_cache.data_version(dependencies), before)

    def test_any_data_change_invalidates(self):
        report = self.templates["total"]
        first = SalesOrder.objects.order_by("pk").first()

        def publish_classification():
            state = ReportClassification.objects.get(pk=1)
            category = next(c for c in state.published["categories"] if c["name"] == "速克達")
            apply_change(state.version, "category", {**category, "name": "T281速克達"}, self.admin)
            state = ReportClassification.objects.get(pk=1)
            apply_change(state.version, "publish", {"token": preview_token(state, self.admin, impact(state.published, state.draft))}, self.admin)

        def save_order():
            first.registration_date = date(2026, 7, 1)
            first.save(update_fields=["registration_date"])  # 不含 updated_at

        def create_order():
            SalesOrder.objects.create(source_type="dealer", source=self.a, order_date=date(2026, 8, 15), registration_date=date(2026, 10, 1),
                                      registration_completed_at=timezone.now(), owner_type="company", owner_name="T281",
                                      vehicle_model=self.model, color=self.color, vehicle_price=1, actual_balance=1, calculated_balance=1,
                                      payment_type="cash", status="completed")

        changes = [
            ("SalesOrder.update 狀態", lambda: SalesOrder.objects.filter(pk=first.pk).update(status="cancelled")),
            ("SalesOrder.update 領牌日", lambda: SalesOrder.objects.filter(pk=first.pk).update(registration_date=date(2026, 6, 1))),
            ("SalesOrder.save update_fields", save_order),
            ("SalesOrder 新增", create_order),
            ("SalesOrder 刪除", lambda: SalesOrder.all_objects.filter(pk=first.pk).delete()),
            ("匯入列 JSON update", lambda: LegacyImportRow.objects.update(mapped_data={"model_number": "GSX-R150"})),
            ("訂單來源類型 update", lambda: SalesOrder.objects.update(source_type="store")),
            ("分類規則發布", publish_classification),
        ]
        for label, change in changes:
            with self.subTest(change=label):
                sid = transaction_savepoint()
                try:
                    before = self.numbers(self.warm(report).context["results"])
                    change()
                    after = self.numbers(self.assert_current(report))
                    self.assertNotEqual(after, before, f"{label} 之後數字或分類應改變")
                finally:
                    transaction_rollback(sid)
                    cache.clear()

    def test_master_data_labels_invalidate(self):
        color_report = self.templates["model-color"]
        before = self.warm(color_report).context["results"]
        VehicleColor.objects.filter(pk=self.color.pk).update(name="T281藍")
        after = self.assert_current(color_report)
        self.assertNotEqual(after, before)
        dealer_report = self.templates["gasoline-dealer"]
        before = self.warm(dealer_report).context["results"]
        SalesSource.objects.filter(pk=self.b.pk).update(name="T281乙車行")
        after = self.assert_current(dealer_report)
        self.assertNotEqual(after, before)
        electric_report = self.templates["electric"]
        before = self.warm(electric_report).context["results"]
        VehicleModel.objects.update(energy_type="electric")
        after = self.assert_current(electric_report)
        self.assertNotEqual(self.numbers(after), self.numbers(before))
        brand_report = self.report
        before = self.warm(brand_report).context["results"]
        VehicleModel.objects.update(brand="T281牌")
        after = self.assert_current(brand_report)
        self.assertEqual(after[0]["rows"][0]["label"], "T281牌")
        self.assertNotEqual(after, before)

    def test_filters_version_and_date_are_part_of_the_key(self):
        report = self.report
        all_rows = self.warm(report).context["results"]
        narrowed = self.page(report, {"source": [str(self.a.pk)]}).context["results"]
        self.assertNotEqual(narrowed[0]["count"], all_rows[0]["count"])
        self.assertEqual(narrowed, self.fresh(report, {"source": [str(self.a.pk)]}).context["results"])
        with mock.patch.object(report_views, "_results", wraps=report_views._results) as computed:
            with mock.patch("config.app_version.get_app_version", return_value="t281-other-build"):
                self.page(report)
            with mock.patch("sales.reporting.cache.timezone.localdate", return_value=timezone.localdate() + timedelta(days=1)):
                self.page(report)
        self.assertEqual(computed.call_count, 2)

    def test_designer_preview_and_cache_failures_compute_directly(self):
        self.warm(self.report)
        with mock.patch.object(report_views, "_results", wraps=report_views._results) as computed:
            report_views.results(self.report.published, {})
        self.assertEqual(computed.call_count, 1, "沒有 report_id（設計器、指令）不走快取")
        expected = self.fresh(self.templates["total"]).context["results"]
        with mock.patch.object(report_cache.cache, "get", side_effect=ConnectionError), \
                mock.patch.object(report_cache.cache, "set", side_effect=ConnectionError):
            for _ in range(3):
                self.assertEqual(self.page(self.templates["total"]).context["results"], expected)

    def test_same_scope_cards_share_totals_query(self):
        report = self.templates["total"]
        with NO_CACHE, CaptureQueriesContext(connection) as captured:
            self.page(report)
        totals = [q for q in captured.captured_queries if re.match(r'SELECT COUNT\("sales_salesorder"\."id"\) AS "count", ', q["sql"])]
        self.assertEqual(len(totals), 1, "四張卡片範圍相同，合計只查一次（原本 4 次）")
        grouped = [q["sql"] for q in captured.captured_queries if "GROUP BY" in q["sql"]]
        self.assertEqual(len(grouped), len(set(grouped)), "完全相同的分組查詢只跑一次")


def transaction_savepoint():
    from django.db import transaction
    return transaction.savepoint()


def transaction_rollback(sid):
    from django.db import transaction
    transaction.savepoint_rollback(sid)
