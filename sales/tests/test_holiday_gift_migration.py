from importlib import import_module

from django.apps import apps
from django.test import TestCase

from sales.models import SalesSource


class HolidayGiftMigrationTests(TestCase):
    def test_legacy_generated_note_becomes_filterable_boolean(self):
        source = SalesSource.objects.create(
            name="待送禮車行",
            source_type=SalesSource.SourceType.DEALER,
            relationship_note="已加入 LINE 群組、需安排年節送禮",
        )
        migration = import_module("sales.migrations.0050_salessource_holiday_gift")

        migration.split_legacy_gift_flag(apps, None)

        source.refresh_from_db()
        self.assertTrue(source.holiday_gift)
        self.assertEqual(source.relationship_note, "已加入 LINE 群組")

        migration.merge_legacy_gift_flag(apps, None)
        source.refresh_from_db()
        self.assertEqual(
            source.relationship_note,
            "已加入 LINE 群組、需安排年節送禮",
        )

    def test_human_written_note_is_not_misclassified(self):
        source = SalesSource.objects.create(
            name="一般備註車行",
            source_type=SalesSource.SourceType.DEALER,
            relationship_note="今年不需安排年節送禮，另行確認",
        )
        migration = import_module("sales.migrations.0050_salessource_holiday_gift")

        migration.split_legacy_gift_flag(apps, None)

        source.refresh_from_db()
        self.assertFalse(source.holiday_gift)
        self.assertEqual(source.relationship_note, "今年不需安排年節送禮，另行確認")

    def test_original_excel_gift_dealers_are_backfilled_by_exact_name(self):
        target = SalesSource.objects.create(
            name="尚勁",
            source_type=SalesSource.SourceType.DEALER,
        )
        untouched = SalesSource.objects.create(
            name="非名單車行",
            source_type=SalesSource.SourceType.DEALER,
        )
        migration = import_module(
            "sales.migrations.0051_backfill_legacy_holiday_gift_dealers"
        )

        migration.backfill_legacy_gift_dealers(apps, None)

        target.refresh_from_db()
        untouched.refresh_from_db()
        self.assertTrue(target.holiday_gift)
        self.assertFalse(untouched.holiday_gift)

        migration.clear_legacy_gift_dealers(apps, None)
        target.refresh_from_db()
        self.assertFalse(target.holiday_gift)
