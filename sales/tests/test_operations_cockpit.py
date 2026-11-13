"""T-167 營運總表駕駛艙（使用者 2026-11-13 選 A 案）。"""
from datetime import date

from django.test import TestCase

from sales.models import Store, VehicleColor, VehicleInventory, VehicleModel
from sales.services.dashboard_metrics import build_dashboard_metrics


def make_vehicle(model, color, status, number, received_on=None):
    store = Store.objects.get_or_create(code="OPS", defaults={"name": "總表測試店"})[0]
    return VehicleInventory.objects.create(
        vehicle_model=model, color=color, engine_number=f"ENG-OPS-{number:05d}", ownership_store=store,
        location_store=store, status=status, received_on=received_on or date(2026, 9, 1))


class InventoryOnHandTests(TestCase):
    """2.6.x「庫存總數」只排除停用，已售出、調出、已交車都被算進去（正式站顯示 1,554，實際在庫 40）。"""

    @classmethod
    def setUpTestData(cls):
        cls.model = VehicleModel.objects.create(brand="測試", name="在庫測試機種", energy_type="gas")
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="白")

    def test_on_hand_counts_only_available_reserved_and_condition_issue(self):
        statuses = ["available", "available", "reserved", "condition_issue",
                    "sold", "transferred_out", "delivered", "inactive"]
        for number, status in enumerate(statuses, start=1):
            make_vehicle(self.model, self.color, status, number)
        inventory = build_dashboard_metrics(date(2026, 9, 12))["inventory"]
        self.assertEqual(inventory["total"], 4)
        self.assertEqual(inventory["available"], 2)
        self.assertEqual(inventory["reserved"], 1)
        self.assertEqual(inventory["issues"], 1)
