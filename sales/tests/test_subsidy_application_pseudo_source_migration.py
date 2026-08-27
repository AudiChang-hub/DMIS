from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class SubsidyApplicationPseudoSourceMigrationTests(TransactionTestCase):
    migrate_from = ("sales", "0091_merge_changsheng_test_ride_source")
    migrate_to = ("sales", "0092_remove_subsidy_application_pseudo_source")

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])
        self.old_apps = self.executor.loader.project_state([self.migrate_from]).apps
        self.addCleanup(self._restore_latest_schema)

    def _restore_latest_schema(self):
        MigrationExecutor(connection).migrate([self.migrate_to])

    def test_pseudo_source_is_moved_to_order_note_and_removed(self):
        SalesSource = self.old_apps.get_model("sales", "SalesSource")
        Profile = self.old_apps.get_model("sales", "SalesSourceCooperationProfile")
        Mapping = self.old_apps.get_model("sales", "LegacyImportMasterMapping")
        VehicleModel = self.old_apps.get_model("sales", "VehicleModel")
        VehicleColor = self.old_apps.get_model("sales", "VehicleColor")
        SalesOrder = self.old_apps.get_model("sales", "SalesOrder")
        Operations = self.old_apps.get_model("sales", "OrderOperationsProfile")
        SearchIndex = self.old_apps.get_model("sales", "SalesOrderSearchIndex")

        source = SalesSource.objects.create(
            name="代申請補助",
            source_type="dealer",
            active=True,
        )
        Profile.objects.create(
            source_id=source.pk,
            cooperation_scope="suzuki_gas",
            cooperates=True,
        )
        Mapping.objects.create(
            source_value="代申請補助",
            normalized_source_value="代申請補助",
            mapping_type="sales_source",
            sales_source_id=source.pk,
            ignored=False,
            updated_by="admin",
        )
        model = VehicleModel.objects.create(
            brand="SUZUKI",
            name="測試車",
            model_number="TEST125",
            energy_type="gas",
            displacement_cc=125,
        )
        color = VehicleColor.objects.create(vehicle_model_id=model.pk, name="白")
        order = SalesOrder.objects.create(
            number="SO-MIGRATION-TEST",
            source_id=source.pk,
            source_type="dealer",
            owner_name="遷移測試",
            owner_phone="0912345678",
            owner_address="新北市",
            owner_id_number="A123456789",
            vehicle_model_id=model.pk,
            color_id=color.pk,
            transaction_type="regular_new",
            note="原備註",
        )
        Operations.objects.create(order_id=order.pk, dealer_name="代申請補助")
        SearchIndex.objects.create(
            order_id=order.pk,
            search_text="合作車行\ndealer\n代申請補助\n原備註",
            match_payload=[
                {"label": "訂單來源", "value": "合作車行", "sensitive": False},
                {"label": "訂單來源", "value": "dealer", "sensitive": False},
                {"label": "來源名稱", "value": "代申請補助", "sensitive": False},
                {"label": "備註", "value": "原備註", "sensitive": False},
            ],
        )

        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_to])
        apps = self.executor.loader.project_state([self.migrate_to]).apps
        SalesSource = apps.get_model("sales", "SalesSource")
        SalesOrder = apps.get_model("sales", "SalesOrder")
        Operations = apps.get_model("sales", "OrderOperationsProfile")
        Mapping = apps.get_model("sales", "LegacyImportMasterMapping")
        SearchIndex = apps.get_model("sales", "SalesOrderSearchIndex")

        self.assertFalse(SalesSource.objects.filter(name="代申請補助").exists())
        migrated_order = SalesOrder.objects.get(pk=order.pk)
        self.assertIsNone(migrated_order.source_id)
        self.assertEqual(migrated_order.source_type, "store")
        self.assertEqual(migrated_order.note, "原備註\n代申請補助")
        self.assertEqual(
            Operations.objects.get(order_id=order.pk).dealer_name,
            "",
        )
        mapping = Mapping.objects.get(source_value="代申請補助")
        self.assertIsNone(mapping.sales_source_id)
        self.assertTrue(mapping.ignored)
        search_index = SearchIndex.objects.get(order_id=order.pk)
        self.assertNotIn(
            {"label": "來源名稱", "value": "代申請補助", "sensitive": False},
            search_index.match_payload,
        )
        self.assertIn(
            {"label": "訂單來源", "value": "本店", "sensitive": False},
            search_index.match_payload,
        )
        self.assertIn(
            {"label": "備註", "value": "原備註\n代申請補助", "sensitive": False},
            search_index.match_payload,
        )

    def test_dongyong_test_ride_source_is_merged_and_note_is_retained(self):
        SalesSource = self.old_apps.get_model("sales", "SalesSource")
        Profile = self.old_apps.get_model("sales", "SalesSourceCooperationProfile")
        Mapping = self.old_apps.get_model("sales", "LegacyImportMasterMapping")
        VehicleModel = self.old_apps.get_model("sales", "VehicleModel")
        VehicleColor = self.old_apps.get_model("sales", "VehicleColor")
        SalesOrder = self.old_apps.get_model("sales", "SalesOrder")
        Operations = self.old_apps.get_model("sales", "OrderOperationsProfile")
        SearchIndex = self.old_apps.get_model("sales", "SalesOrderSearchIndex")

        canonical = SalesSource.objects.create(
            name="東永",
            code="DONGYONG",
            source_type="dealer",
            active=True,
        )
        legacy = SalesSource.objects.create(
            name="東永(試乘車)",
            source_type="dealer",
            active=True,
        )
        Profile.objects.create(
            source_id=legacy.pk,
            cooperation_scope="suzuki_gas",
            cooperates=False,
        )
        Mapping.objects.create(
            source_value="東永(試乘車)",
            normalized_source_value="東永(試乘車)",
            mapping_type="sales_source",
            sales_source_id=legacy.pk,
            ignored=False,
            updated_by="admin",
        )
        model = VehicleModel.objects.create(
            brand="SUZUKI",
            name="東永測試車",
            model_number="DONGYONG125",
            energy_type="gas",
            displacement_cc=125,
        )
        color = VehicleColor.objects.create(vehicle_model_id=model.pk, name="白")
        order = SalesOrder.objects.create(
            number="SO-DONGYONG-TEST",
            source_id=canonical.pk,
            source_type="dealer",
            owner_name="東永試乘",
            owner_phone="0912345678",
            owner_address="新北市",
            owner_id_number="A123456789",
            vehicle_model_id=model.pk,
            color_id=color.pk,
            transaction_type="test_ride",
            note="原備註",
        )
        Operations.objects.create(order_id=order.pk, dealer_name="東永")
        SearchIndex.objects.create(
            order_id=order.pk,
            search_text="合作車行\n東永\n原備註",
            match_payload=[
                {"label": "來源名稱", "value": "東永", "sensitive": False},
                {"label": "備註", "value": "原備註", "sensitive": False},
            ],
        )

        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_to])
        apps = self.executor.loader.project_state([self.migrate_to]).apps
        SalesSource = apps.get_model("sales", "SalesSource")
        SalesOrder = apps.get_model("sales", "SalesOrder")
        Mapping = apps.get_model("sales", "LegacyImportMasterMapping")
        SearchIndex = apps.get_model("sales", "SalesOrderSearchIndex")

        self.assertFalse(SalesSource.objects.filter(name="東永(試乘車)").exists())
        migrated_order = SalesOrder.objects.get(pk=order.pk)
        self.assertEqual(migrated_order.source_id, canonical.pk)
        self.assertEqual(migrated_order.transaction_type, "test_ride")
        self.assertEqual(migrated_order.note, "原備註\n試乘車")
        mapping = Mapping.objects.get(source_value="東永(試乘車)")
        self.assertEqual(mapping.sales_source_id, canonical.pk)
        self.assertEqual(mapping.note, "特殊訂單註記：試乘車（通路已正規化）")
        search_index = SearchIndex.objects.get(order_id=order.pk)
        self.assertIn("試乘車", search_index.search_text)
        self.assertIn(
            {"label": "備註", "value": "原備註\n試乘車", "sensitive": False},
            search_index.match_payload,
        )
