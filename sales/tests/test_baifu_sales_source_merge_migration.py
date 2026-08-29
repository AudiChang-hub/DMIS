from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class BaifuSalesSourceMergeMigrationTests(TransactionTestCase):
    migrate_from = ("sales", "0099_shared_dealer_vehicle_capacity")
    migrate_to = ("sales", "0100_merge_baifu_sales_sources")

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])
        self.old_apps = self.executor.loader.project_state([self.migrate_from]).apps
        self.addCleanup(self._restore_latest_schema)

    def _restore_latest_schema(self):
        MigrationExecutor(connection).migrate([self.migrate_to])

    def test_duplicate_baifu_is_merged_and_legacy_name_is_mapped(self):
        SalesSource = self.old_apps.get_model("sales", "SalesSource")
        Profile = self.old_apps.get_model(
            "sales", "SalesSourceCooperationProfile"
        )
        Mapping = self.old_apps.get_model("sales", "LegacyImportMasterMapping")

        canonical = SalesSource.objects.create(
            name="百福(馳機)",
            source_type="dealer",
            code="S26031919",
            responsible_person="王小明",
            phone="24561234",
            has_line_group=True,
            active=True,
        )
        legacy = SalesSource.objects.create(
            name="百福",
            source_type="dealer",
            address="基隆市七堵區測試路1號",
            holiday_gift=True,
            sym_vehicle_capacity=2,
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
            note="歷史合作資料",
        )
        Mapping.objects.create(
            source_value="百福",
            normalized_source_value="百福",
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
            SalesSource.objects.filter(source_type="dealer", name="百福").exists()
        )
        merged = SalesSource.objects.get(
            source_type="dealer", name="百福(馳機)"
        )
        self.assertEqual(merged.pk, canonical.pk)
        self.assertEqual(merged.address, "基隆市七堵區測試路1號")
        self.assertTrue(merged.holiday_gift)
        self.assertTrue(merged.has_line_group)
        self.assertEqual(merged.sym_vehicle_capacity, 2)
        sym = Profile.objects.get(source_id=merged.pk, cooperation_scope="sym")
        self.assertTrue(sym.cooperates)
        self.assertEqual(sym.relationship_type, "exclusive")
        self.assertEqual(sym.note, "歷史合作資料")
        mapping = Mapping.objects.get(
            mapping_type="sales_source", normalized_source_value="百福"
        )
        self.assertEqual(mapping.sales_source_id, merged.pk)
        self.assertFalse(mapping.ignored)

