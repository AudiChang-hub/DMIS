from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ChangshengSalesSourceMergeMigrationTests(TransactionTestCase):
    migrate_from = ("sales", "0090_merge_yijun_sales_sources")
    migrate_to = ("sales", "0091_merge_changsheng_test_ride_source")

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])
        self.old_apps = self.executor.loader.project_state([self.migrate_from]).apps
        self.addCleanup(self._restore_latest_schema)

    def _restore_latest_schema(self):
        MigrationExecutor(connection).migrate([self.migrate_to])

    def test_trial_source_is_merged_and_mapping_is_preserved(self):
        SalesSource = self.old_apps.get_model("sales", "SalesSource")
        Profile = self.old_apps.get_model("sales", "SalesSourceCooperationProfile")
        Mapping = self.old_apps.get_model("sales", "LegacyImportMasterMapping")

        canonical = SalesSource.objects.create(
            name="昌勝",
            source_type="dealer",
            code="N26032512",
            responsible_person="吳金鋒",
            active=True,
        )
        legacy = SalesSource.objects.create(
            name="昌勝(試乘車)",
            source_type="dealer",
            has_line_group=True,
            active=True,
        )
        Profile.objects.create(
            source_id=legacy.pk,
            cooperation_scope="suzuki_gas",
            cooperates=True,
            vehicle_capacity=1,
        )
        Mapping.objects.create(
            source_value="昌勝(試乘車)",
            normalized_source_value="昌勝(試乘車)",
            mapping_type="sales_source",
            sales_source_id=legacy.pk,
            ignored=False,
            updated_by="admin",
        )

        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_to])
        apps = self.executor.loader.project_state([self.migrate_to]).apps
        SalesSource = apps.get_model("sales", "SalesSource")
        Profile = apps.get_model("sales", "SalesSourceCooperationProfile")
        Mapping = apps.get_model("sales", "LegacyImportMasterMapping")

        self.assertFalse(
            SalesSource.objects.filter(
                source_type="dealer", name="昌勝(試乘車)"
            ).exists()
        )
        merged = SalesSource.objects.get(source_type="dealer", name="昌勝")
        self.assertEqual(merged.pk, canonical.pk)
        self.assertTrue(merged.has_line_group)
        self.assertTrue(
            Profile.objects.filter(
                source_id=merged.pk,
                cooperation_scope="suzuki_gas",
                cooperates=True,
                vehicle_capacity=1,
            ).exists()
        )
        self.assertEqual(
            Mapping.objects.get(source_value="昌勝(試乘車)").sales_source_id,
            merged.pk,
        )
