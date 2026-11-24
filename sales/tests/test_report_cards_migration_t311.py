"""T-311 migration 0227：#5 電動車、#7 油車銷售統計改成 B 案圖卡（月份圖型號在前、加銷售來源圓餅）。

只改內建原樣的這兩張；自建或改過的報表不動；可重跑；reverse 還原原本三張；設定與 source_templates 一致。
"""
import copy
from contextlib import ExitStack
from importlib import import_module
from unittest import mock

from django.apps import apps as global_apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader
from django.test import SimpleTestCase, TransactionTestCase, tag

from sales.management.commands.check_migration_compat import migration_issues
from sales.reporting.engine import validate_config
from sales.reporting.source_templates import (
    electric_platform_sales, electric_vehicle_sales, gasoline_vehicle_sales, total_vehicle_sales,
)

BEFORE = ("sales", "0226_t309_compulsory_insurance_gift")
AFTER = ("sales", "0227_t311_energy_sales_cards")
migration = import_module("sales.migrations.0227_t311_energy_sales_cards")


def legacy(config):
    """T-311 之前的內建設定：每月銷售來源、每月銷售型號、型號占比三張。"""
    old = copy.deepcopy(config)
    model, source, donut, _added = old["cards"]
    old["cards"] = [source, model, donut]
    return old


class EnergySalesCardTransformTests(SimpleTestCase):
    def test_migration_is_safe_while_previous_version_runs(self):
        loader = MigrationLoader(None, ignore_no_migrations=True)
        self.assertEqual(migration_issues(loader, [AFTER]), [])

    def test_upgrade_matches_templates_and_only_reorders_plus_one_donut(self):
        for template, vehicle in ((electric_vehicle_sales, "電動車"), (gasoline_vehicle_sales, "油車")):
            with self.subTest(vehicle=vehicle):
                new = template()
                old = legacy(new)
                self.assertEqual([card["series"] for card in old["cards"][:2]], ["legacy_sales_source", "legacy_model"])
                self.assertEqual(migration.upgraded(old), new)
                self.assertEqual(new["cards"][3], {"title": f"{vehicle}銷售來源占比", "chart": "donut", "dimension": "legacy_sales_source",
                                                   "metric": "count", "formula": "", "limit": 10, "sort": "value"})
                self.assertEqual(migration.downgraded(new), old)
                validate_config(new)

    def test_upgrade_is_idempotent_and_skips_everything_else(self):
        new = electric_vehicle_sales()
        self.assertIsNone(migration.upgraded(new))  # 已是新樣子
        old = legacy(new)
        for change in (
            lambda c: c.update(title="我的電動車報表"),                     # 自建（標題不同）
            lambda c: c.update(audience="team"),
            lambda c: c.update(reader_layout="standard"),
            lambda c: c["fixed_filters"].update(legacy_energy=["油車"]),   # 版型與能源別不符
            lambda c: c["cards"].pop(),                                     # 改過圖卡
            lambda c: c["cards"][2].update(chart="bar"),
            lambda c: c["cards"][0].update(series="legacy_dealer"),
        ):
            changed = copy.deepcopy(old)
            change(changed)
            self.assertIsNone(migration.upgraded(changed))
        self.assertIsNone(migration.upgraded(total_vehicle_sales()))  # #4 不改設定
        renamed = copy.deepcopy(new)
        renamed["cards"][3]["title"] = "改過的圓餅"
        self.assertIsNone(migration.downgraded(renamed))  # 管理者改過新增的圓餅就不還原

    def test_platform_and_dealer_pages_keep_the_source_month_card(self):
        # 平台、車行頁以「每月銷售來源」為底；T-311 調了電動車頁的順序，它們的圖卡不能跟著變。
        card = electric_platform_sales()["cards"][0]
        self.assertEqual((card["limit"], card["series_limit"], card["series"], card["title"]), (24, 10, "legacy_dealer", "電動車平台每月銷售"))
        self.assertNotIn("width", card)


@tag("migration")
class EnergySalesCardMigrationTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(self._restore_latest_schema)

    def _restore_latest_schema(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_forward_backward_and_rerun(self):
        executor = MigrationExecutor(connection)
        executor.migrate([BEFORE])
        apps = executor.loader.project_state([BEFORE]).apps
        Report = apps.get_model("sales", "ReportDefinition")
        Revision = apps.get_model("sales", "ReportRevision")
        electric, gasoline = legacy(electric_vehicle_sales()), legacy(gasoline_vehicle_sales())
        own = {**copy.deepcopy(electric), "title": "自建電動車報表"}
        drafted = copy.deepcopy(gasoline)
        drafted_draft = {**copy.deepcopy(gasoline), "description": "管理者還沒發布的草稿"}
        reports = {
            "electric": Report.objects.create(draft=copy.deepcopy(electric), published=copy.deepcopy(electric), version=3),
            "gasoline": Report.objects.create(draft=drafted_draft, published=drafted, version=2),
            "own": Report.objects.create(draft=copy.deepcopy(own), published=copy.deepcopy(own), version=1),
            "total": Report.objects.create(draft=total_vehicle_sales(), published=total_vehicle_sales(), version=1),
        }

        executor = MigrationExecutor(connection)
        executor.migrate([AFTER])
        Report = executor.loader.project_state([AFTER]).apps.get_model("sales", "ReportDefinition")
        current = {key: Report.objects.get(pk=report.pk) for key, report in reports.items()}
        self.assertEqual(current["electric"].published, electric_vehicle_sales())
        self.assertEqual(current["electric"].draft, electric_vehicle_sales())
        self.assertEqual(current["electric"].version, 4)
        self.assertEqual(current["gasoline"].published, gasoline_vehicle_sales())
        self.assertEqual(current["gasoline"].draft, drafted_draft)  # 未發布的草稿不動
        self.assertEqual((current["own"].published, current["own"].version), (own, 1))
        self.assertEqual((current["total"].published, current["total"].version), (total_vehicle_sales(), 1))
        revision = Revision.objects.get(report_id=reports["electric"].pk, version=4)
        self.assertEqual((revision.action, revision.config), ("publish", electric_vehicle_sales()))

        # 重跑不再改（版本不再增加）
        migration.forwards(executor.loader.project_state([AFTER]).apps, type("Editor", (), {"connection": connection})())
        self.assertEqual(Report.objects.get(pk=reports["electric"].pk).version, 4)

        executor = MigrationExecutor(connection)
        executor.migrate([BEFORE])
        Report = executor.loader.project_state([BEFORE]).apps.get_model("sales", "ReportDefinition")
        restored = Report.objects.get(pk=reports["electric"].pk)
        self.assertEqual((restored.published, restored.draft, restored.version), (electric, electric, 5))
        self.assertEqual(Report.objects.get(pk=reports["gasoline"].pk).published, gasoline)
        self.assertEqual(Report.objects.get(pk=reports["own"].pk).published, own)


@tag("migration")
class EnergySalesCardMigrationTransactionTests(TransactionTestCase):
    """PostgreSQL 的 select_for_update 在 autocommit 下會丟 TransactionManagementError；SQLite 不支援，所以測不出來。
    在 SQLite 上模擬「支援 select_for_update」（CI 的 PostgreSQL 步驟則是真的），確認 forwards／backwards 不論怎麼被呼叫都自己開交易。"""

    def _simulate_select_for_update(self):
        if connection.features.has_select_for_update:
            return  # PostgreSQL：直接用真的
        stack = ExitStack()
        stack.enter_context(mock.patch.object(connection.features, "has_select_for_update", True))
        stack.enter_context(mock.patch.object(connection.ops, "for_update_sql", lambda *args, **kwargs: ""))
        self.addCleanup(stack.close)

    def test_forwards_and_backwards_outside_a_transaction(self):
        from sales.models import ReportDefinition

        electric = legacy(electric_vehicle_sales())
        report = ReportDefinition.objects.create(draft=copy.deepcopy(electric), published=copy.deepcopy(electric), version=1)
        self._simulate_select_for_update()
        self.assertTrue(connection.get_autocommit())
        editor = type("Editor", (), {"connection": connection})()

        migration.forwards(global_apps, editor)
        report.refresh_from_db()
        self.assertEqual((report.published, report.version), (electric_vehicle_sales(), 2))

        migration.backwards(global_apps, editor)
        report.refresh_from_db()
        self.assertEqual((report.published, report.version), (electric, 3))
