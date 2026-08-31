from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class EmployeePurchasePlatformToStoreMigrationTests(TransactionTestCase):
    migrate_from = ("sales", "0101_merge_special_platform_sources")
    migrate_to = ("sales", "0102_convert_employee_purchase_platforms_to_store")

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])
        self.old_apps = self.executor.loader.project_state([self.migrate_from]).apps
        self.addCleanup(self._restore_latest_schema)

    def _restore_latest_schema(self):
        MigrationExecutor(connection).migrate([self.migrate_to])

    def test_only_confirmed_employee_purchase_platforms_become_store_orders(self):
        SalesSource = self.old_apps.get_model("sales", "SalesSource")
        Mapping = self.old_apps.get_model("sales", "LegacyImportMasterMapping")
        VehicleModel = self.old_apps.get_model("sales", "VehicleModel")
        VehicleColor = self.old_apps.get_model("sales", "VehicleColor")
        SalesOrder = self.old_apps.get_model("sales", "SalesOrder")
        Operations = self.old_apps.get_model("sales", "OrderOperationsProfile")
        SearchIndex = self.old_apps.get_model("sales", "SalesOrderSearchIndex")

        source_names = (
            "上海商銀員購",
            "台新銀員購",
            "台新銀行員購",
            "華新麗華員購",
        )
        target_sources = {
            name: SalesSource.objects.create(
                name=name, source_type="platform", active=True
            )
            for name in source_names
        }
        unrelated = SalesSource.objects.create(
            name="博客來", source_type="platform", active=True
        )
        model = VehicleModel.objects.create(
            brand="SUZUKI",
            name="員購遷移測試車",
            model_number="EMPLOYEE-PURCHASE-TEST",
            energy_type="gas",
            displacement_cc=125,
        )
        color = VehicleColor.objects.create(vehicle_model_id=model.pk, name="白")

        order_ids = {}
        for index, source_name in enumerate(source_names, start=1):
            source = target_sources[source_name]
            Mapping.objects.update_or_create(
                mapping_type="sales_source",
                normalized_source_value=source_name.casefold(),
                defaults={
                    "source_value": source_name,
                    "sales_source_id": source.pk,
                    "vehicle_model_id": None,
                    "ignored": False,
                    "note": "",
                    "updated_by": "admin",
                },
            )
            order = SalesOrder.objects.create(
                number=f"SO-EMPLOYEE-PURCHASE-{index}",
                source_id=source.pk,
                source_type="platform",
                owner_name="員購遷移測試",
                owner_phone="0912345678",
                owner_address="台北市",
                owner_id_number="A123456789",
                vehicle_model_id=model.pk,
                color_id=color.pk,
                transaction_type="regular_new",
                note=(
                    "原備註"
                    if index == 1
                    else source_name if index == 2 else ""
                ),
            )
            order_ids[source_name] = order.pk
            Operations.objects.create(order_id=order.pk, dealer_name=source_name)
            SearchIndex.objects.create(
                order_id=order.pk,
                search_text=f"網路平台\nplatform\n{source_name}",
                match_payload=[
                    {"label": "訂單來源", "value": "網路平台", "sensitive": False},
                    {"label": "來源名稱", "value": source_name, "sensitive": False},
                ],
            )

        unrelated_order = SalesOrder.objects.create(
            number="SO-EMPLOYEE-PURCHASE-OTHER",
            source_id=unrelated.pk,
            source_type="platform",
            owner_name="其他平台測試",
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

        for source_name in source_names:
            self.assertFalse(
                SalesSource.objects.filter(
                    source_type="platform", name=source_name
                ).exists()
            )
            migrated_order = SalesOrder.objects.get(pk=order_ids[source_name])
            self.assertIsNone(migrated_order.source_id)
            self.assertEqual(migrated_order.source_type, "store")
            expected_note = (
                f"原備註\n{source_name}"
                if source_name == "上海商銀員購"
                else source_name
            )
            self.assertEqual(migrated_order.note, expected_note)
            self.assertEqual(
                Operations.objects.get(order_id=migrated_order.pk).dealer_name,
                "",
            )
            mapping = Mapping.objects.get(
                mapping_type="sales_source",
                normalized_source_value=source_name.casefold(),
            )
            self.assertIsNone(mapping.sales_source_id)
            self.assertTrue(mapping.ignored)
            self.assertEqual(
                mapping.note,
                f"特殊平台註記：{source_name}（改列本店訂單）",
            )
            search_index = SearchIndex.objects.get(order_id=migrated_order.pk)
            self.assertIn("本店", search_index.search_text)
            self.assertIn("store", search_index.search_text)
            self.assertIn(source_name, search_index.search_text)
            self.assertNotIn(
                {"label": "來源名稱", "value": source_name, "sensitive": False},
                search_index.match_payload,
            )
            self.assertIn(
                {"label": "備註", "value": source_name, "sensitive": False},
                search_index.match_payload,
            )

        self.assertTrue(
            SalesSource.objects.filter(
                pk=unrelated.pk,
                source_type="platform",
                name="博客來",
            ).exists()
        )
        unchanged_order = SalesOrder.objects.get(pk=unrelated_order.pk)
        self.assertEqual(unchanged_order.source_id, unrelated.pk)
        self.assertEqual(unchanged_order.source_type, "platform")
        self.assertEqual(unchanged_order.note, "原樣保留")
