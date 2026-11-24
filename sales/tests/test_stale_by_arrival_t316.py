"""T-316：滯銷改看進車日期（使用者 2026-11-24 定義）。

滯銷＝車型最早進車那台在庫車從進車日（received_on）起已放 ≥ 90 天，而且從那天到今天這個車型都沒賣出（以領牌計）。
不再用「近 90 天 0 台」或「預估可銷 > 90 天」判定；剛進的車不會因為以前沒賣過就被標滯銷。
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import SalesOrder, VehicleColor, VehicleModel
from sales.services import operations_cockpit
from sales.tests.test_operations_cockpit import make_vehicle


class StaleByArrivalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.model = VehicleModel.objects.create(brand="測試", name="T316 V-STROM", energy_type="gas")
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="白")

    def setUp(self):
        cache.clear()
        self.today = timezone.localdate()
        self.number = 0

    def vehicle(self, days_ago):
        self.number += 1
        make_vehicle(self.model, self.color, "available", 31600 + self.number,
                     received_on=self.today - timedelta(days=days_ago))

    def sale(self, days_ago):
        day = self.today - timedelta(days=days_ago)
        SalesOrder.objects.create(
            owner_name="T316 合成", owner_phone="0912345678", owner_address="合成地址", owner_id_number="A123456789",
            vehicle_model=self.model, color=self.color, registration_date=day, established_on=day,
            status="completed", vehicle_price=150000, registration_completed_at=timezone.now())

    def row(self):
        rows = {row["model_id"]: row for row in operations_cockpit.model_velocity(self.today)}
        return rows[self.model.pk]

    def test_just_arrived_and_never_sold_is_not_slow(self):
        self.vehicle(10)
        self.vehicle(10)
        self.assertFalse(self.row()["slow"])

    def test_parked_95_days_without_sale_since_arrival_is_slow(self):
        self.vehicle(95)
        self.sale(120)   # 進車前賣過不算
        row = self.row()
        self.assertTrue(row["slow"])
        self.assertEqual(row["stale_days"], 95)

    def test_parked_95_days_but_sold_after_arrival_is_not_slow(self):
        self.vehicle(95)
        self.vehicle(95)
        self.sale(50)    # 舊規則：在庫 2、近 90 天 1 台 → 預估 180 天 > 90 → 滯銷
        self.assertFalse(self.row()["slow"])

    def test_oldest_arrival_decides(self):
        self.vehicle(95)
        self.vehicle(10)
        self.assertTrue(self.row()["slow"])
        self.assertEqual(self.row()["stale_days"], 95)
        self.sale(60)    # 最早那台進車後有賣出
        self.assertFalse(self.row()["slow"])

    def test_threshold_is_90_days(self):
        self.vehicle(89)
        self.assertFalse(self.row()["slow"])

    def test_page_shows_parked_days_and_plain_rule(self):
        self.vehicle(95)
        admin = get_user_model().objects.create_superuser("t316-admin", password="test-only")
        self.client.force_login(admin)
        html = self.client.get(reverse("operations_report")).content.decode()
        self.assertIn('<span class="ops-cover__main"><em class="ops-tag ops-tag--amber">滯銷</em></span>'
                      '<small class="ops-cover__why">已放 95 天沒賣出</small></span>', html)
        self.assertIn("車放了 90 天以上，從進車到現在這個車型都沒賣出＝滯銷", html)
        self.assertNotIn("預估超過 90 天或 90 天沒賣出＝滯銷", html)

    def test_page_young_unsold_row_has_no_slow_tag(self):
        self.vehicle(10)
        admin = get_user_model().objects.create_superuser("t316-admin", password="test-only")
        self.client.force_login(admin)
        html = self.client.get(reverse("operations_report")).content.decode()
        start = html.index('aria-labelledby="ops-stock-title"')
        card = html[start:html.index("</section>", start)]
        self.assertNotIn("ops-tag--amber", card)
