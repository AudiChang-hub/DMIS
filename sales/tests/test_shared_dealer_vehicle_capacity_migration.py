from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class SharedDealerVehicleCapacityMigrationTests(TransactionTestCase):
    migrate_from = ("sales", "0098_salessource_region")
    migrate_to = ("sales", "0099_shared_dealer_vehicle_capacity")

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])
        self.old_apps = self.executor.loader.project_state([self.migrate_from]).apps
        self.addCleanup(self._restore_latest_schema)

    def _restore_latest_schema(self):
        MigrationExecutor(connection).migrate([self.migrate_to])

    def test_suzuki_gas_and_electric_capacity_is_collapsed_to_one_shared_value(self):
        SalesSource = self.old_apps.get_model("sales", "SalesSource")
        Profile = self.old_apps.get_model(
            "sales", "SalesSourceCooperationProfile"
        )
        source = SalesSource.objects.create(
            name="冠廷",
            source_type="dealer",
            vehicle_capacity=5,
        )
        Profile.objects.create(
            source_id=source.pk,
            cooperation_scope="sym",
            cooperates=True,
            vehicle_capacity=5,
        )
        Profile.objects.create(
            source_id=source.pk,
            cooperation_scope="suzuki_gas",
            cooperates=True,
            vehicle_capacity=3,
        )
        Profile.objects.create(
            source_id=source.pk,
            cooperation_scope="suzuki_electric",
            cooperates=True,
            vehicle_capacity=3,
        )

        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_to])
        apps = self.executor.loader.project_state([self.migrate_to]).apps
        migrated = apps.get_model("sales", "SalesSource").objects.get(pk=source.pk)

        self.assertEqual(migrated.sym_vehicle_capacity, 5)
        self.assertEqual(migrated.suzuki_vehicle_capacity, 3)
