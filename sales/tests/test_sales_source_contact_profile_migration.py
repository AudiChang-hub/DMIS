from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class SalesSourceContactProfileMigrationTests(TransactionTestCase):
    migrate_from = ("sales", "0087_consolidate_sales_source_notes")
    migrate_to = ("sales", "0088_sales_source_contact_and_cooperation_profiles")

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])
        self.old_apps = self.executor.loader.project_state([self.migrate_from]).apps
        self.addCleanup(self._restore_latest_schema)

    def _restore_latest_schema(self):
        MigrationExecutor(connection).migrate([self.migrate_to])

    def test_legacy_contact_and_current_cooperation_are_preserved(self):
        SalesSource = self.old_apps.get_model("sales", "SalesSource")
        SalesSourceBrandPolicy = self.old_apps.get_model(
            "sales", "SalesSourceBrandPolicy"
        )
        source = SalesSource.objects.create(
            name="測試車行",
            source_type="dealer",
            phone="02-12345678",
            fax="02-87654321",
            vehicle_capacity=5,
            note=(
                "重要合作車行\n"
                "歷史聯絡資料：王先生（負責人）｜電話：02-11112222／"
                "手機：0912345678／Email：owner@example.com"
            ),
        )
        SalesSourceBrandPolicy.objects.create(
            source_id=source.pk,
            cooperation_scope="sym",
            cooperates=True,
            effective_from=date(2026, 1, 1),
        )
        SalesSourceBrandPolicy.objects.create(
            source_id=source.pk,
            cooperation_scope="suzuki_gas",
            cooperates=False,
            effective_from=date(2026, 1, 2),
        )

        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_to])
        apps = self.executor.loader.project_state([self.migrate_to]).apps
        migrated = apps.get_model("sales", "SalesSource").objects.get(pk=source.pk)
        Profile = apps.get_model("sales", "SalesSourceCooperationProfile")

        self.assertEqual(migrated.responsible_person, "王先生")
        self.assertEqual(migrated.phone, "02-12345678")
        self.assertEqual(migrated.mobile, "0912345678")
        self.assertIn("owner@example.com", migrated.other_contact)
        self.assertIn("02-87654321", migrated.other_contact)
        profiles = {
            item.cooperation_scope: item
            for item in Profile.objects.filter(source_id=source.pk)
        }
        self.assertTrue(profiles["sym"].cooperates)
        self.assertEqual(profiles["sym"].vehicle_capacity, 5)
        self.assertFalse(profiles["suzuki_gas"].cooperates)
        self.assertIsNone(profiles["suzuki_gas"].vehicle_capacity)
        self.assertFalse(profiles["suzuki_electric"].cooperates)
