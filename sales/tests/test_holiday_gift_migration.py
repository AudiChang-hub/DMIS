from importlib import import_module

from django.apps import apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from sales.models import SalesSource


class HolidayGiftFieldMigrationTests(TransactionTestCase):
    migrate_from = (
        "sales",
        "0049_paymentrecord_payment_order_confirmed_idx_and_more",
    )
    migrate_to = ("sales", "0050_salessource_holiday_gift")
    restore_to = ("sales", "0088_sales_source_contact_and_cooperation_profiles")

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

    def test_exact_legacy_gift_note_becomes_filterable_boolean(self):
        SalesSource = self.old_apps.get_model("sales", "SalesSource")
        source = SalesSource.objects.create(
            name="待送禮車行",
            source_type="dealer",
            relationship_note="已加入 LINE 群組、需安排年節送禮",
        )

        new_apps = self._migrate()
        migrated = new_apps.get_model("sales", "SalesSource").objects.get(pk=source.pk)

        self.assertTrue(migrated.holiday_gift)
        self.assertEqual(migrated.relationship_note, "已加入 LINE 群組")

    def test_human_written_note_is_not_misclassified(self):
        SalesSource = self.old_apps.get_model("sales", "SalesSource")
        source = SalesSource.objects.create(
            name="一般備註車行",
            source_type="dealer",
            relationship_note="今年不需安排年節送禮，另行確認",
        )

        new_apps = self._migrate()
        migrated = new_apps.get_model("sales", "SalesSource").objects.get(pk=source.pk)

        self.assertFalse(migrated.holiday_gift)
        self.assertEqual(
            migrated.relationship_note,
            "今年不需安排年節送禮，另行確認",
        )


class HolidayGiftMigrationTests(TestCase):
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
