"""T-332 migration：牌險手續費支出只擴充，資料庫層預設 0，舊單補 0、上一版不帶這欄的寫入也不失敗。"""
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader
from django.test import SimpleTestCase, TransactionTestCase, tag

from sales.management.commands.check_migration_compat import migration_issues
from sales.models import OrderOperationsProfile
from sales.tests import test_order_flow as flow

BEFORE = ("sales", "0228_t320_proxy_delivery_transaction_type")
AFTER = ("sales", "0229_t332_plate_insurance_fee_expense")
TABLE = "sales_orderoperationsprofile"
COLUMN = "plate_insurance_fee_expense"


class PlateInsuranceFeeExpenseCompatTests(SimpleTestCase):
    def test_migration_is_safe_while_previous_version_runs(self):
        loader = MigrationLoader(None, ignore_no_migrations=True)
        self.assertEqual(migration_issues(loader, [AFTER]), [])

    def test_migration_only_adds_this_field(self):
        loader = MigrationLoader(None, ignore_no_migrations=True)
        operations = loader.get_migration(*AFTER).operations
        self.assertEqual([(type(op).__name__, op.model_name, op.name) for op in operations],
                         [("AddField", "orderoperationsprofile", COLUMN)])


@tag("migration")
class PlateInsuranceFeeExpenseMigrationTests(TransactionTestCase):
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
            description = connection.introspection.get_table_description(cursor, TABLE)
        return next((row for row in description if row.name == COLUMN), None)

    def test_existing_profiles_get_zero_and_profit_is_unchanged(self):
        order = self.make_order()
        OrderOperationsProfile.objects.filter(order=order).update(
            actual_disbursement=80000, vehicle_cost=61000, gift_expense=400)
        before_profit = OrderOperationsProfile.objects.get(order=order).net_profit
        executor = MigrationExecutor(connection)
        executor.migrate([BEFORE])
        self.assertIsNone(self.column())
        executor = MigrationExecutor(connection)
        executor.migrate([AFTER])
        column = self.column()
        self.assertIsNotNone(column)
        self.assertFalse(column.null_ok)
        # 資料庫層預設 0：上一版程式新增收支資料時不帶這欄也不會失敗。
        self.assertIn("0", str(column.default))
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT {COLUMN} FROM {TABLE} WHERE order_id = %s", [order.pk])
            self.assertEqual(Decimal(cursor.fetchone()[0]), 0)
        self._restore_latest_schema()
        self.assertEqual(OrderOperationsProfile.objects.get(order=order).net_profit, before_profit)
