from importlib import import_module

from django.apps import apps
from django.test import TestCase

from sales.models import (
    VehicleFactoryModelCode,
    VehicleModel,
    VehicleModelFamily,
)


class DrZ4smMigrationTests(TestCase):
    def test_existing_machine_and_factory_codes_are_consolidated(self):
        family = VehicleModelFamily.objects.create(
            brand="SUZUKI",
            name="暫存機種",
        )
        VehicleModelFamily.objects.filter(pk=family.pk).update(name="DR-Z4SM")

        first = VehicleModel.objects.create(
            brand="SUZUKI",
            name="暫存機種",
            family=family,
            model_number="TEMP-2025",
            model_year=2025,
            model_code=VehicleModel.ModelType.ABS_DUAL_DISC,
            energy_type=VehicleModel.EnergyType.GAS,
            displacement_cc=398,
        )
        second = VehicleModel.objects.create(
            brand="SUZUKI",
            name="暫存機種",
            family=family,
            model_number="TEMP-2026",
            model_year=2026,
            model_code=VehicleModel.ModelType.ABS_DUAL_DISC,
            energy_type=VehicleModel.EnergyType.GAS,
            displacement_cc=398,
        )
        VehicleModel.objects.filter(pk=first.pk).update(
            family_id=family.pk,
            name="DR-Z4SM",
            model_number="DR-Z4SM",
        )
        VehicleModel.objects.filter(pk=second.pk).update(
            family_id=family.pk,
            name="DRZ-4SM",
            model_number="DRZ-4SM",
        )
        VehicleFactoryModelCode.objects.filter(code__startswith="TEMP-20").delete()

        canonical_code = VehicleFactoryModelCode.objects.create(
            family=family,
            code="DR-Z4SM",
        )
        legacy_code = VehicleFactoryModelCode.objects.create(
            family=family,
            code="TEMP-CODE",
        )
        VehicleFactoryModelCode.objects.filter(pk=legacy_code.pk).update(
            code="DRZ-4SM",
            normalized_code="drz-4sm",
        )
        first.factory_model_codes.set([canonical_code])
        second.factory_model_codes.set([legacy_code])

        migration = import_module("sales.migrations.0068_canonicalize_dr_z4sm")
        migration.forwards(apps, None)

        family.refresh_from_db()
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(family.name, "DR-Z4SM (滑胎版)")
        self.assertEqual(first.name, "DR-Z4SM (滑胎版)")
        self.assertEqual(second.name, "DR-Z4SM (滑胎版)")
        self.assertEqual(first.model_number, "DR-Z4SM")
        self.assertEqual(second.model_number, "DR-Z4SM")
        self.assertEqual(VehicleFactoryModelCode.objects.count(), 1)
        self.assertEqual(
            list(first.factory_model_codes.values_list("code", flat=True)),
            ["DR-Z4SM"],
        )
        self.assertEqual(
            list(second.factory_model_codes.values_list("code", flat=True)),
            ["DR-Z4SM"],
        )
