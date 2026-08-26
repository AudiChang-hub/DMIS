from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class SalesSourceLineGroupMigrationTests(TransactionTestCase):
    migrate_from = ("sales", "0085_clean_legacy_odoo_note_markers")
    migrate_to = ("sales", "0086_sales_source_line_group")
    restore_to = ("sales", "0087_consolidate_sales_source_notes")

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])
        self.old_apps = self.executor.loader.project_state([self.migrate_from]).apps
        self.addCleanup(self._restore_latest_schema)

    def _restore_latest_schema(self):
        MigrationExecutor(connection).migrate([self.restore_to])

    def _migrate(self):
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_to])
        return self.executor.loader.project_state([self.migrate_to]).apps

    def test_exact_legacy_marker_is_extracted_and_other_note_is_preserved(self):
        SalesSource = self.old_apps.get_model("sales", "SalesSource")
        source = SalesSource.objects.create(
            name="測試車行",
            source_type="dealer",
            relationship_note="已加入 LINE 群組、重要合作車行",
        )

        new_apps = self._migrate()
        migrated = new_apps.get_model("sales", "SalesSource").objects.get(pk=source.pk)

        self.assertTrue(migrated.has_line_group)
        self.assertEqual(migrated.line_group_scope, "")
        self.assertEqual(migrated.relationship_note, "重要合作車行")

    def test_similar_free_text_is_not_misclassified(self):
        SalesSource = self.old_apps.get_model("sales", "SalesSource")
        source = SalesSource.objects.create(
            name="人工備註車行",
            source_type="dealer",
            relationship_note="已加入 LINE 群組但尚待確認窗口",
        )

        new_apps = self._migrate()
        migrated = new_apps.get_model("sales", "SalesSource").objects.get(pk=source.pk)

        self.assertFalse(migrated.has_line_group)
        self.assertEqual(
            migrated.relationship_note,
            "已加入 LINE 群組但尚待確認窗口",
        )
