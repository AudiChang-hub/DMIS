from importlib import import_module

from django.apps import apps
from django.test import TestCase

from sales.models import (
    VehicleFactoryModelCode,
    VehicleModel,
    VehicleModelFamily,
)


class DrZ4sMigrationTests(TestCase):
    def test_migration_canonicalizes_model_number_and_factory_codes(self):
        family = VehicleModelFamily.objects.create(
            brand="SUZUKI",
            name="DR-Z4S (越野版)",
        )
        model = VehicleModel.objects.create(
            brand="SUZUKI",
            name="DR-Z4S (越野版)",
            model_number="TEMP",
            model_year=2026,
            family=family,
        )
        VehicleModel.objects.filter(pk=model.pk).update(model_number="DRZ-4S")

        first = model.factory_model_codes.get()
        second = VehicleFactoryModelCode.objects.create(
            family=family,
            code="TEMP-2",
            normalized_code="temp-2",
        )
        VehicleFactoryModelCode.objects.filter(pk=first.pk).update(
            code="DRZ-4S", normalized_code="drz-4s"
        )
        VehicleFactoryModelCode.objects.filter(pk=second.pk).update(
            code="DR-Z4S", normalized_code="dr-z4s"
        )
        first.versions.add(model)
        second.versions.add(model)

        migration = import_module(
            "sales.migrations.0069_canonicalize_dr_z4s_model_number"
        )
        migration.forwards(apps, None)

        model.refresh_from_db()
        self.assertEqual(model.name, "DR-Z4S (越野版)")
        self.assertEqual(model.model_number, "DR-Z4S")
        self.assertEqual(
            list(
                VehicleFactoryModelCode.objects.filter(family=family).values_list(
                    "code", flat=True
                )
            ),
            ["DR-Z4S"],
        )
        self.assertEqual(
            list(model.factory_model_codes.values_list("code", flat=True)),
            ["DR-Z4S"],
        )
