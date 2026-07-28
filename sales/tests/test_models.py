from django.core.exceptions import ValidationError
from django.test import TestCase

from sales.models import Store, VehicleColor, VehicleInventory, VehicleModel


class InventoryValidationTests(TestCase):
    def setUp(self):
        self.store = Store.objects.create(name="總店", code="HQ")
        self.electric = VehicleModel.objects.create(
            brand="測試", name="電動一號", energy_type=VehicleModel.EnergyType.ELECTRIC
        )
        self.color = VehicleColor.objects.create(
            vehicle_model=self.electric, name="藍"
        )

    def test_electric_vehicle_uses_frame_number(self):
        vehicle = VehicleInventory.objects.create(
            vehicle_model=self.electric,
            color=self.color,
            frame_number="ev-frame-001",
            ownership_store=self.store,
            location_store=self.store,
        )

        self.assertEqual(vehicle.frame_number, "EV-FRAME-001")
        self.assertIsNone(vehicle.engine_number)

    def test_duplicate_identifier_is_rejected(self):
        VehicleInventory.objects.create(
            vehicle_model=self.electric,
            color=self.color,
            frame_number="EV-001",
            ownership_store=self.store,
            location_store=self.store,
        )
        duplicate = VehicleInventory(
            vehicle_model=self.electric,
            color=self.color,
            frame_number="ev-001",
            ownership_store=self.store,
            location_store=self.store,
        )

        with self.assertRaises(ValidationError):
            duplicate.save()

