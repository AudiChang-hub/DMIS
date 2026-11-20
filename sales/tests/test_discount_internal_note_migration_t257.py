"""T-257 migration：discount_internal_note 只擴充，資料庫層預設空字串，舊版程式照常寫入。"""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader
from django.test import SimpleTestCase, TransactionTestCase, tag

from sales.management.commands.check_migration_compat import migration_issues
from sales.tests import test_order_flow as flow

BEFORE = ("sales", "0220_t238b_drop_source_code_columns")
AFTER = ("sales", "0221_t257_discount_internal_note")
COLUMN = "discount_internal_note"


class DiscountInternalNoteCompatTests(SimpleTestCase):
    def test_migration_is_safe_while_previous_version_runs(self):
        loader = MigrationLoader(None, ignore_no_migrations=True)
        self.assertEqual(migration_issues(loader, [AFTER]), [])


@tag("migration")
class DiscountInternalNoteMigrationTests(TransactionTestCase):
    setUp_fixtures = flow.OrderFlowTests.setUp
    make_order = flow.OrderFlowTests.make_order

    def setUp(self):
        super().setUp()
        self.setUp_fixtures()
        self.addCleanup(self._restore_latest_schema)

    def _restore_latest_schema(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def column(self):
        with connection.cursor() as cursor:
            description = connection.introspection.get_table_description(cursor, "sales_salesorder")
        return next((row for row in description if row.name == COLUMN), None)

    def test_existing_orders_get_blank_note_and_column_has_db_default(self):
        order = self.make_order()
        executor = MigrationExecutor(connection)
        executor.migrate([BEFORE])
        self.assertIsNone(self.column())
        executor = MigrationExecutor(connection)
        executor.migrate([AFTER])
        column = self.column()
        self.assertIsNotNone(column)
        self.assertFalse(column.null_ok)
        # 資料庫層預設空字串（PostgreSQL 回 ''::character varying），上一版不帶這欄的 INSERT 也不會失敗。
        self.assertIn("''", str(column.default))
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT {COLUMN} FROM sales_salesorder WHERE id = %s", [order.pk])
            self.assertEqual(cursor.fetchone()[0], "")
