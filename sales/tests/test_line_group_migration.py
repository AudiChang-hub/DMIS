from importlib import import_module

from django.apps import apps
from django.test import TestCase

from sales.models import SalesSource


line_group_migration = import_module("sales.migrations.0086_sales_source_line_group")


class SalesSourceLineGroupMigrationTests(TestCase):
    def test_split_extracts_exact_legacy_marker_and_preserves_other_notes(self):
        source = SalesSource.objects.create(
            name="測試車行",
            source_type=SalesSource.SourceType.DEALER,
            relationship_note="已加入 LINE 群組、重要合作車行",
        )

        line_group_migration.split_legacy_line_group_flag(apps, None)

        source.refresh_from_db()
        self.assertTrue(source.has_line_group)
        self.assertEqual(source.line_group_scope, "")
        self.assertEqual(source.relationship_note, "重要合作車行")

    def test_split_does_not_classify_similar_free_text_as_system_marker(self):
        source = SalesSource.objects.create(
            name="人工備註車行",
            source_type=SalesSource.SourceType.DEALER,
            relationship_note="已加入 LINE 群組但尚待確認窗口",
        )

        line_group_migration.split_legacy_line_group_flag(apps, None)

        source.refresh_from_db()
        self.assertFalse(source.has_line_group)
        self.assertEqual(source.relationship_note, "已加入 LINE 群組但尚待確認窗口")

    def test_reverse_restores_marker_without_overwriting_notes(self):
        source = SalesSource.objects.create(
            name="回復測試車行",
            source_type=SalesSource.SourceType.DEALER,
            has_line_group=True,
            line_group_scope=SalesSource.LineGroupScope.ALL,
            relationship_note="重要合作車行",
        )

        line_group_migration.merge_legacy_line_group_flag(apps, None)

        source.refresh_from_db()
        self.assertEqual(source.relationship_note, "已加入 LINE 群組、重要合作車行")
