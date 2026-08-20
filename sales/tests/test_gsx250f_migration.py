from datetime import date
from decimal import Decimal
from importlib import import_module

from django.apps import apps
from django.test import TestCase

from sales.models import (
    VehicleColor,
    VehicleFactoryModelCode,
    VehicleModel,
    VehicleModelFamily,
    VehiclePriceVersion,
)


class Gsx250fMigrationTests(TestCase):
    def test_alias_versions_are_merged_without_losing_business_data(self):
        family = VehicleModelFamily.objects.create(
            brand="SUZUKI",
            name="GIXXER SF 250 ABS",
        )
        target = VehicleModel.objects.create(
            brand="SUZUKI",
            name=family.name,
            family=family,
            model_number="GSX250F",
            model_year=2022,
            model_code=VehicleModel.ModelType.ABS_DUAL_DISC,
            energy_type=VehicleModel.EnergyType.GAS,
            displacement_cc=249,
            base_dealer_commission=0,
        )
        source = VehicleModel.objects.create(
            brand="SUZUKI",
            name=family.name,
            family=family,
            model_number="TEMP-ALIAS",
            model_year=2022,
            model_code="",
            energy_type=VehicleModel.EnergyType.GAS,
            displacement_cc=None,
            base_dealer_commission=5000,
        )
        VehicleModel.objects.filter(pk=source.pk).update(
            model_number="GSX250F GIXXER SF 250"
        )
        VehiclePriceVersion.objects.create(
            vehicle_model=source,
            suggested_price=0,
            cash_price=148000,
            effective_from=date(2026, 4, 9),
        )
        VehicleColor.objects.create(vehicle_model=target, name="藍", active=False)
        VehicleColor.objects.create(vehicle_model=source, name="藍", active=True)
        VehicleColor.objects.create(vehicle_model=source, name="Moto GP 藍", active=True)
        alias_code = VehicleFactoryModelCode.objects.create(
            family=family,
            code="TEMP-CODE",
        )
        VehicleFactoryModelCode.objects.filter(pk=alias_code.pk).update(
            code="GSX250F GIXXER SF 250",
            normalized_code="gsx250fgixxersf250",
        )
        source.factory_model_codes.set([alias_code])
        family.factory_model_codes.filter(versions__isnull=True).delete()

        other_year = VehicleModel.objects.create(
            brand="SUZUKI",
            name=family.name,
            family=family,
            model_number="TEMP-2024",
            model_year=2024,
            model_code=VehicleModel.ModelType.ABS_DUAL_DISC,
            energy_type=VehicleModel.EnergyType.GAS,
            displacement_cc=249,
        )
        VehicleModel.objects.filter(pk=other_year.pk).update(
            model_number="GSX250F GIXXER SF 250"
        )
        other_year.factory_model_codes.set([alias_code])
        family.factory_model_codes.filter(versions__isnull=True).delete()

        migration = import_module(
            "sales.migrations.0074_canonicalize_gsx250f_model_number"
        )
        migration.forwards(apps, None)

        target.refresh_from_db()
        other_year.refresh_from_db()
        self.assertFalse(VehicleModel.objects.filter(pk=source.pk).exists())
        self.assertEqual(target.model_number, "GSX250F")
        self.assertEqual(target.base_dealer_commission, Decimal("5000"))
        self.assertEqual(target.displacement_cc, 249)
        self.assertEqual(target.price_versions.get().cash_price, Decimal("148000"))
        self.assertEqual(
            list(target.colors.order_by("name").values_list("name", "active")),
            [("Moto GP 藍", True), ("藍", True)],
        )
        self.assertEqual(other_year.model_number, "GSX250F")
        self.assertEqual(
            list(family.factory_model_codes.values_list("code", flat=True)),
            ["GSX250F"],
        )
