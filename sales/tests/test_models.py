from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from sales.models import (
    Store,
    SalesOrder,
    VehicleColor,
    VehicleInventory,
    VehicleModel,
    VehiclePriceVersion,
)
from sales.services.price_version import (
    apply_order_price_snapshot,
    resolve_vehicle_price_version,
)


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
        self.assertEqual(vehicle.normalized_frame_number, "EVFRAME001")
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

    def test_identifier_duplicate_ignores_spaces_and_hyphens(self):
        VehicleInventory.objects.create(
            vehicle_model=self.electric,
            color=self.color,
            frame_number="EV-001 A",
            ownership_store=self.store,
            location_store=self.store,
        )
        duplicate = VehicleInventory(
            vehicle_model=self.electric,
            color=self.color,
            frame_number="ev 001-a",
            ownership_store=self.store,
            location_store=self.store,
        )

        with self.assertRaises(ValidationError):
            duplicate.save()

    def test_manufactured_year_month_requires_year_and_month(self):
        vehicle = VehicleInventory(
            vehicle_model=self.electric,
            color=self.color,
            frame_number="EV-MONTH-1",
            manufactured_year_month="2026-08",
            ownership_store=self.store,
            location_store=self.store,
        )

        with self.assertRaises(ValidationError):
            vehicle.save()


class VehiclePriceVersionTests(TestCase):
    def setUp(self):
        self.model = VehicleModel.objects.create(
            brand="測試",
            name="通勤車",
            energy_type=VehicleModel.EnergyType.GAS,
            displacement_cc=125,
        )

    def test_price_fields_are_independent_and_not_derived(self):
        version = VehiclePriceVersion.objects.create(
            vehicle_model=self.model,
            suggested_retail_price=Decimal("77000"),
            cash_price_including_registration=Decimal("72000"),
            cash_price_excluding_registration=Decimal("70000"),
            cash_purchase_bonus=Decimal("5000"),
            effective_from=date(2026, 8, 1),
        )

        self.assertEqual(version.cash_price_excluding_registration, Decimal("70000"))

    def test_end_date_cannot_precede_start_date(self):
        version = VehiclePriceVersion(
            vehicle_model=self.model,
            effective_from=date(2026, 8, 1),
            effective_to=date(2026, 7, 31),
        )

        with self.assertRaises(ValidationError):
            version.save()

    def test_resolver_uses_order_date_and_snapshot_does_not_change_sale_price(self):
        old_version = VehiclePriceVersion.objects.create(
            vehicle_model=self.model,
            cash_price_excluding_registration=Decimal("70000"),
            effective_from=date(2026, 8, 1),
            effective_to=date(2026, 8, 31),
        )
        VehiclePriceVersion.objects.create(
            vehicle_model=self.model,
            cash_price_excluding_registration=Decimal("71000"),
            effective_from=date(2026, 9, 1),
        )
        color = VehicleColor.objects.create(vehicle_model=self.model, name="灰")
        order = SalesOrder.objects.create(
            order_date=date(2026, 8, 20),
            owner_name="價格快照測試",
            owner_phone="0911000000",
            owner_address="新北市",
            owner_id_number="A123456789",
            vehicle_model=self.model,
            color=color,
            vehicle_price=Decimal("69500"),
        )

        self.assertEqual(
            resolve_vehicle_price_version(self.model.pk, order.order_date),
            old_version,
        )
        apply_order_price_snapshot(order)
        order.refresh_from_db()
        self.assertEqual(order.vehicle_price, Decimal("69500"))
        self.assertEqual(order.price_version, old_version)
        self.assertEqual(
            order.price_snapshot["cash_price_excluding_registration"],
            "70000",
        )

        old_version.cash_price_excluding_registration = Decimal("68000")
        old_version.save()
        order.refresh_from_db()
        self.assertEqual(
            order.price_snapshot["cash_price_excluding_registration"],
            "70000",
        )

