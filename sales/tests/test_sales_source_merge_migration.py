from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class SalesSourceMergeMigrationTests(TransactionTestCase):
    migrate_from = ("sales", "0089_remove_salessource_line_group_scope")
    migrate_to = ("sales", "0090_merge_yijun_sales_sources")

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])
        self.old_apps = self.executor.loader.project_state([self.migrate_from]).apps
        self.addCleanup(self._restore_latest_schema)

    def _restore_latest_schema(self):
        MigrationExecutor(connection).migrate([self.migrate_to])

    def test_duplicate_dealers_are_merged_without_losing_profiles_or_mapping(self):
        SalesSource = self.old_apps.get_model("sales", "SalesSource")
        Profile = self.old_apps.get_model(
            "sales", "SalesSourceCooperationProfile"
        )
        Mapping = self.old_apps.get_model("sales", "LegacyImportMasterMapping")

        canonical = SalesSource.objects.create(
            name="奕鈞工坊",
            source_type="dealer",
            code="N26032522",
            responsible_person="張奕鈞",
            phone="24258317",
            active=True,
        )
        legacy = SalesSource.objects.create(
            name="奕鈞",
            source_type="dealer",
            mobile="0928745549",
            holiday_gift=True,
            has_line_group=True,
            active=True,
        )
        Profile.objects.create(
            source_id=canonical.pk,
            cooperation_scope="sym",
            cooperates=False,
            relationship_type="general",
        )
        Profile.objects.create(
            source_id=legacy.pk,
            cooperation_scope="sym",
            cooperates=True,
            relationship_type="exclusive",
            vehicle_capacity=3,
            note="舊主檔合作資料",
        )
        Profile.objects.create(
            source_id=legacy.pk,
            cooperation_scope="suzuki_gas",
            cooperates=True,
        )
        Mapping.objects.create(
            source_value="奕鈞",
            normalized_source_value="奕鈞",
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
            SalesSource.objects.filter(source_type="dealer", name="奕鈞").exists()
        )
        merged = SalesSource.objects.get(
            source_type="dealer", name="奕鈞工坊"
        )
        self.assertEqual(merged.pk, canonical.pk)
        self.assertEqual(merged.mobile, "0928745549")
        self.assertTrue(merged.holiday_gift)
        self.assertTrue(merged.has_line_group)
        sym = Profile.objects.get(source_id=merged.pk, cooperation_scope="sym")
        self.assertTrue(sym.cooperates)
        self.assertEqual(sym.relationship_type, "exclusive")
        self.assertEqual(sym.vehicle_capacity, 3)
        self.assertEqual(sym.note, "舊主檔合作資料")
        self.assertTrue(
            Profile.objects.filter(
                source_id=merged.pk, cooperation_scope="suzuki_gas"
            ).exists()
        )
        self.assertEqual(Mapping.objects.get(source_value="奕鈞").sales_source_id, merged.pk)
