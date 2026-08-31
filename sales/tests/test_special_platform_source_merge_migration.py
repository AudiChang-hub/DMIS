from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class SpecialPlatformSourceMergeMigrationTests(TransactionTestCase):
    migrate_from = ("sales", "0100_merge_baifu_sales_sources")
    migrate_to = ("sales", "0101_merge_special_platform_sources")

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])
        self.old_apps = self.executor.loader.project_state([self.migrate_from]).apps
        self.addCleanup(self._restore_latest_schema)

    def _restore_latest_schema(self):
        MigrationExecutor(connection).migrate([self.migrate_to])

    def test_only_confirmed_special_platforms_are_merged_into_order_notes(self):
        SalesSource = self.old_apps.get_model("sales", "SalesSource")
        Mapping = self.old_apps.get_model("sales", "LegacyImportMasterMapping")
        VehicleModel = self.old_apps.get_model("sales", "VehicleModel")
        VehicleColor = self.old_apps.get_model("sales", "VehicleColor")
        SalesOrder = self.old_apps.get_model("sales", "SalesOrder")
        Operations = self.old_apps.get_model("sales", "OrderOperationsProfile")
        SearchIndex = self.old_apps.get_model("sales", "SalesOrderSearchIndex")

        rules = (
            ("momo", "momo員購"),
            ("小樹購", "小樹購員購"),
            ("Yahoo", "Yahoo+假展場"),
        )
        canonical_sources = {
            name: SalesSource.objects.create(
                name=name, source_type="platform", active=True
            )
            for name, _legacy_name in rules
        }
        unrelated = SalesSource.objects.create(
            name="上海商銀員購", source_type="platform", active=True
        )
        model = VehicleModel.objects.create(
            brand="SUZUKI",
            name="平台遷移測試車",
            model_number="PLATFORM-TEST",
            energy_type="gas",
            displacement_cc=125,
        )
        color = VehicleColor.objects.create(vehicle_model_id=model.pk, name="白")

        order_ids = {}
        for index, (canonical_name, legacy_name) in enumerate(rules, start=1):
            legacy = SalesSource.objects.create(
                name=legacy_name, source_type="platform", active=True
            )
            Mapping.objects.create(
                source_value=legacy_name,
                normalized_source_value=legacy_name.casefold(),
                mapping_type="sales_source",
                sales_source_id=legacy.pk,
                ignored=False,
                updated_by="admin",
            )
            order = SalesOrder.objects.create(
                number=f"SO-PLATFORM-{index}",
                source_id=legacy.pk,
                source_type="platform",
                owner_name="平台遷移測試",
                owner_phone="0912345678",
                owner_address="新北市",
                owner_id_number="A123456789",
                vehicle_model_id=model.pk,
                color_id=color.pk,
                transaction_type="regular_new",
                note=(
                    "原備註"
                    if index == 1
                    else legacy_name if index == 2 else ""
                ),
            )
            order_ids[legacy_name] = order.pk
            Operations.objects.create(order_id=order.pk, dealer_name=legacy_name)
            SearchIndex.objects.create(
                order_id=order.pk,
                search_text=f"網路平台\n{legacy_name}",
                match_payload=[
                    {"label": "來源名稱", "value": legacy_name, "sensitive": False}
                ],
            )

        unrelated_order = SalesOrder.objects.create(
            number="SO-PLATFORM-OTHER",
            source_id=unrelated.pk,
            source_type="platform",
            owner_name="其他員購測試",
            owner_phone="0912345678",
            owner_address="台北市",
            owner_id_number="A123456789",
            vehicle_model_id=model.pk,
            color_id=color.pk,
            transaction_type="regular_new",
            note="原樣保留",
        )

        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_to])
        apps = self.executor.loader.project_state([self.migrate_to]).apps
        SalesSource = apps.get_model("sales", "SalesSource")
        SalesOrder = apps.get_model("sales", "SalesOrder")
        Operations = apps.get_model("sales", "OrderOperationsProfile")
        Mapping = apps.get_model("sales", "LegacyImportMasterMapping")
        SearchIndex = apps.get_model("sales", "SalesOrderSearchIndex")

        for canonical_name, legacy_name in rules:
            self.assertFalse(
                SalesSource.objects.filter(
                    source_type="platform", name=legacy_name
                ).exists()
            )
            migrated_order = SalesOrder.objects.get(pk=order_ids[legacy_name])
            self.assertEqual(
                migrated_order.source_id, canonical_sources[canonical_name].pk
            )
            expected_note = (
                f"原備註\n{legacy_name}"
                if legacy_name == "momo員購"
                else legacy_name
            )
            self.assertEqual(migrated_order.note, expected_note)
            self.assertEqual(
                Operations.objects.get(order_id=migrated_order.pk).dealer_name,
                canonical_name,
            )
            mapping = Mapping.objects.get(
                mapping_type="sales_source",
                normalized_source_value=legacy_name.casefold(),
            )
            self.assertEqual(mapping.sales_source_id, canonical_sources[canonical_name].pk)
            self.assertFalse(mapping.ignored)
            search_index = SearchIndex.objects.get(order_id=migrated_order.pk)
            self.assertIn(canonical_name, search_index.search_text)
            self.assertIn(legacy_name, search_index.search_text)
            self.assertIn(
                {"label": "備註", "value": legacy_name, "sensitive": False},
                search_index.match_payload,
            )

        self.assertTrue(
            SalesSource.objects.filter(
                pk=unrelated.pk,
                source_type="platform",
                name="上海商銀員購",
            ).exists()
        )
        self.assertEqual(
            SalesOrder.objects.get(pk=unrelated_order.pk).note, "原樣保留"
        )
