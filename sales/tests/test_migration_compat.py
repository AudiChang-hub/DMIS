from io import StringIO
from types import SimpleNamespace

from django.core.management import call_command
from django.db import migrations, models
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.state import ModelState, ProjectState
from django.test import SimpleTestCase, TestCase

from sales.management.commands.check_migration_compat import migration_issues, operation_issues


def widget_state():
    state = ProjectState()
    state.add_model(
        ModelState(
            "demo",
            "widget",
            [
                ("id", models.AutoField(primary_key=True)),
                ("note", models.CharField(max_length=10, null=True)),
                ("code", models.CharField(max_length=10)),
            ],
        )
    )
    return state


def issues(operation):
    return operation_issues(operation, "demo", widget_state(), set())


class OperationCompatibilityTests(SimpleTestCase):
    def test_expand_operations_are_safe_while_old_version_runs(self):
        safe = [
            migrations.AddField("widget", "memo", models.CharField(max_length=20, null=True)),
            migrations.AddField("widget", "flag", models.BooleanField(default=False, db_default=False)),
            migrations.AlterField("widget", "code", models.CharField(max_length=40, verbose_name="代碼")),
            migrations.AlterField("widget", "code", models.CharField(max_length=10, null=True)),
            migrations.RunPython(migrations.RunPython.noop),
            migrations.AddIndex("widget", models.Index(fields=["code"], name="widget_code_idx")),
            # 收斂前一步：只從 model 拿掉欄位，資料庫欄位留著（舊版仍可讀寫）。
            migrations.SeparateDatabaseAndState(state_operations=[migrations.RemoveField("widget", "note")]),
        ]
        for operation in safe:
            with self.subTest(operation=operation.describe()):
                self.assertEqual(issues(operation), [])

    def test_contract_operations_break_old_version(self):
        breaking = [
            migrations.RemoveField("widget", "note"),
            migrations.RenameField("widget", "code", "sku"),
            migrations.DeleteModel("widget"),
            migrations.RenameModel("widget", "gadget"),
            migrations.RunSQL("ALTER TABLE demo_widget DROP COLUMN note"),
            migrations.AddField("widget", "flag", models.BooleanField(default=False)),
            migrations.AlterField("widget", "note", models.CharField(max_length=10)),
            migrations.AlterField("widget", "code", models.IntegerField()),
            migrations.AlterField("widget", "code", models.CharField(max_length=10, db_column="sku")),
            migrations.SeparateDatabaseAndState(database_operations=[migrations.RemoveField("widget", "note")]),
        ]
        for operation in breaking:
            with self.subTest(operation=operation.describe()):
                self.assertEqual(len(issues(operation)), 1)

    def test_new_table_in_same_batch_is_not_used_by_old_version(self):
        self.assertEqual(
            operation_issues(
                migrations.AddField("widget", "flag", models.BooleanField(default=False)),
                "demo",
                widget_state(),
                {("demo", "widget")},
            ),
            [],
        )

    def test_reviewed_contract_migration_can_be_marked_safe(self):
        migration = SimpleNamespace(
            app_label="demo",
            operations=[migrations.RemoveField("widget", "note")],
        )
        loader = SimpleNamespace(
            graph=SimpleNamespace(nodes={("demo", "0002"): migration}),
            project_state=lambda key, at_end: widget_state(),
        )
        self.assertEqual(len(migration_issues(loader, [("demo", "0002")])), 1)
        migration.zero_downtime_safe = True
        self.assertEqual(migration_issues(loader, [("demo", "0002")]), [])


class ProjectMigrationCompatibilityTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.loader = MigrationLoader(None, ignore_no_migrations=True)

    def test_known_project_migrations_are_classified(self):
        self.assertEqual(
            migration_issues(self.loader, [("sales", "0192_plate_choice_watch_label")]), []
        )
        removed = migration_issues(self.loader, [("sales", "0194_remove_salesorder_vehicle_category")])
        self.assertEqual([reason for _, _, reason in removed], ["刪除欄位，舊版仍會讀寫它"])


class CommandTests(TestCase):
    def test_nothing_pending_after_test_database_is_migrated(self):
        output = StringIO()
        call_command("check_migration_compat", stdout=output)
        self.assertIn("沒有待套用的 migration", output.getvalue())

    def test_explicit_breaking_migration_exits_with_code_3(self):
        output = StringIO()
        with self.assertRaises(SystemExit) as raised:
            call_command(
                "check_migration_compat", "sales.0194_remove_salesorder_vehicle_category", stdout=output
            )
        self.assertEqual(raised.exception.code, 3)
        self.assertIn("vehicle_category", output.getvalue())
