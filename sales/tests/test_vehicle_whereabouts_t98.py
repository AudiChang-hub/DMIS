"""已交車／售出／調出的車不再顯示「目前位置：本店」（使用者 2026-10-22 T-98）。

交車只改車輛狀態、不改存放欄位，所以畫面改看 VehicleInventory.whereabouts_label；
歷史紀錄的位置快照仍用 actual_location_label，存放欄位與資料都不動。
"""

import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import SalesOrder, SalesSource, Store, VehicleColor, VehicleInventory, VehicleModel
from sales.services.order_search import build_order_search_payload

Status = VehicleInventory.Status


class VehicleWhereaboutsTests(TestCase):
    def setUp(self):
        from sales.services.print_company import initialize_company

        self.user = get_user_model().objects.create_superuser("t98", "", "test-pass-123")
        self.client.force_login(self.user)
        self.store = Store.objects.create(name="總店", code="HQ")
        self.model = VehicleModel.objects.create(brand="SUZUKI", name="SUI 125", energy_type=VehicleModel.EnergyType.GAS)
        self.color = VehicleColor.objects.create(vehicle_model=self.model, name="灰")
        self.dealer = SalesSource.objects.create(name="馭盛車行", source_type=SalesSource.SourceType.DEALER)
        self.order = SalesOrder(
            owner_name="王小明", owner_phone="0912345678", owner_address="新北市汐止區", owner_id_number="A123456789",
            vehicle_model=self.model, color=self.color, vehicle_price=Decimal("75000"), deposit_amount=Decimal("5000"),
            actual_balance=Decimal("70000"), id_verified=True, status=SalesOrder.Status.ALLOCATION_PENDING,
        )
        initialize_company(self.order, self.user)
        self.order.save()
        self.vehicle = self.make_vehicle("ENG-T98")
        self.order.allocate(self.vehicle)

    def make_vehicle(self, engine, **extra):
        return VehicleInventory.objects.create(
            vehicle_model=self.model, color=self.color, engine_number=engine,
            ownership_store=self.store, location_store=self.store, **extra,
        )

    def location_card(self):
        html = self.client.get(reverse("order_detail", args=[self.order.pk])).content.decode()
        card = re.search(r'<div class="allocation-overview__location[^"]*">.*?</div>\s*</div>', html, re.S)
        self.assertIsNotNone(card)
        return card.group(0)

    def deliver(self):
        delivered_at = timezone.make_aware(timezone.datetime(2026, 10, 21, 15, 0))
        VehicleInventory.objects.filter(pk=self.vehicle.pk).update(status=Status.DELIVERED)
        SalesOrder.objects.filter(pk=self.order.pk).update(status=SalesOrder.Status.COMPLETED, delivered_at=delivered_at)
        self.vehicle.refresh_from_db()
        self.order.refresh_from_db()

    def test_labels_follow_vehicle_status(self):
        cases = (
            (dict(status=Status.AVAILABLE), "本店", False),
            (dict(status=Status.AVAILABLE, current_dealer=self.dealer), "馭盛車行", False),
            (dict(status=Status.DELIVERED), "已交車給客戶", True),
            (dict(status=Status.SOLD), "已售出", True),
            (dict(status=Status.SOLD, disposition=VehicleInventory.Disposition.DEALER_PICKUP, disposition_dealer_name="工廠"), "工廠已領車", True),
            (dict(status=Status.TRANSFERRED_OUT, disposition=VehicleInventory.Disposition.TRANSFER_OUT, disposition_dealer=self.dealer), "已調出：馭盛車行", True),
            (dict(status=Status.TRANSFERRED_OUT), "已調出", True),
        )
        for index, (fields, label, left) in enumerate(cases):
            with self.subTest(label=label):
                vehicle = VehicleInventory(**fields)
                self.assertEqual(vehicle.whereabouts_label, label)
                self.assertEqual(vehicle.has_left_store, left)
                # 存放欄位本身不變：歷史快照仍記錄離開前的位置。
                self.assertEqual(vehicle.actual_location_label, "馭盛車行" if fields.get("current_dealer") else "本店")

    def test_allocated_vehicle_still_shows_current_location(self):
        card = self.location_card()
        self.assertIn("目前位置", card)
        self.assertIn("<strong>本店</strong>", card)
        self.assertNotIn("is-left", card)

    def test_delivered_order_shows_whereabouts_instead_of_store(self):
        self.deliver()
        card = self.location_card()
        self.assertIn("車輛去向", card)
        self.assertIn("<strong>已交車給客戶</strong>", card)
        self.assertIn("2026/10/21 交付，已不在本店", card)
        self.assertIn("is-left", card)
        self.assertNotIn("本店</strong>", card)
        html = self.client.get(reverse("order_detail", args=[self.order.pk])).content.decode()
        self.assertIn("已交付給本訂單客戶", html)
        self.assertEqual(VehicleInventory.objects.get(pk=self.vehicle.pk).location_store, self.store)

    def test_search_payload_and_receipt_list_use_whereabouts(self):
        self.deliver()
        payload = str(build_order_search_payload(self.order))
        self.assertIn("已交車給客戶", payload)
        html = self.client.get(reverse("inventory_receipt_list")).content.decode()
        self.assertIn('<td data-label="實際位置">已交車給客戶</td>', html)
