"""T-326：庫存「實際位置」按「復原」放回剛才的位置，剛才的車行已停用也允許。

其他情況照 T-308 規則：不能改到已停用的車行。例外只認改位置成功時伺服器簽發的復原憑證，
而且車在那之後沒被改過、放回的正是剛才的車行。資料全部虛構。
"""
from django.contrib.auth import get_user_model
from django.core import signing
from django.test import TestCase
from django.urls import reverse

from sales.inventory_location_views import UNDO_SALT
from sales.models import SalesSource, Store, VehicleColor, VehicleInventory, VehicleModel

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


class InventoryLocationUndoToInactiveDealerTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin", password="Local-t326-417!"))
        self.store = Store.objects.create(name="馭盛", code="HQ")  # 本店門市依名稱辨識（sales/services/home_stores.py）
        self.closed = SalesSource.objects.create(name="停用示範車行", source_type=SalesSource.SourceType.DEALER, active=False)
        self.other_closed = SalesSource.objects.create(
            name="停用示範車行乙", source_type=SalesSource.SourceType.DEALER, active=False,
        )
        self.open_dealer = SalesSource.objects.create(name="示範車行丙", source_type=SalesSource.SourceType.DEALER)
        model = VehicleModel.objects.create(brand="SYM", name="示範車型 125", model_number="T326")
        color = VehicleColor.objects.create(vehicle_model=model, name="消光黑")
        self.car = VehicleInventory.objects.create(
            vehicle_model=model, color=color, frame_number="T3260001", ownership_store=self.store,
            location_store=self.store, current_dealer=self.closed,
        )
        self.home = f"home-{self.store.pk}"

    def post(self, location, car=None, **extra):
        car = car or self.car
        return self.client.post(reverse("inventory_location", args=[car.pk]), {"location": location, **extra}, **AJAX)

    def move_home(self):
        payload = self.post(self.home, expected=str(self.closed.pk)).json()
        self.assertEqual((payload["ok"], payload["changed"]), (True, True))
        self.assertTrue(payload["undo_token"])
        return payload

    def undo(self, token, location=None, **extra):
        return self.post(location or str(self.closed.pk), expected=self.home, undo="1", undo_token=token, **extra)

    def test_undo_puts_car_back_at_inactive_dealer_it_just_left(self):
        payload = self.move_home()
        self.assertEqual(payload["previous_value"], str(self.closed.pk))
        response = self.undo(payload["undo_token"])
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual((body["ok"], body["changed"], body["value"], body["label"]), (True, True, str(self.closed.pk), "停用示範車行"))
        self.car.refresh_from_db()
        self.assertEqual((self.car.current_dealer, self.car.location_store), (self.closed, self.store))
        self.assertEqual(
            list(self.car.history_entries.order_by("pk").values_list("reason", flat=True)), ["改位置", "改位置（復原）"],
        )

    def test_moving_to_inactive_dealer_without_undo_is_still_rejected(self):
        token = self.move_home()["undo_token"]
        for extra in ({}, {"undo_token": token}, {"undo": "1"}):
            with self.subTest(extra=extra):
                response = self.post(str(self.closed.pk), expected=self.home, **extra)
                self.assertEqual(response.status_code, 400)
        self.car.refresh_from_db()
        self.assertIsNone(self.car.current_dealer)

    def test_undo_token_only_allows_the_dealer_the_car_just_left(self):
        token = self.move_home()["undo_token"]
        self.assertEqual(self.undo(token, location=str(self.other_closed.pk)).status_code, 400)
        self.car.refresh_from_db()
        self.assertIsNone(self.car.current_dealer)

    def test_tampered_or_foreign_token_is_rejected(self):
        self.move_home()
        other_car = VehicleInventory.objects.create(
            vehicle_model=self.car.vehicle_model, color=self.car.color, frame_number="T3260002",
            ownership_store=self.store, location_store=self.store,
        )
        foreign = signing.dumps(
            {"car": other_car.pk, "from": [self.closed.pk, self.store.pk], "to": [None, self.store.pk]}, salt=UNDO_SALT,
        )
        wrong_salt = signing.dumps(
            {"car": self.car.pk, "from": [self.closed.pk, self.store.pk], "to": [None, self.store.pk]}, salt="other",
        )
        for token in ("", "abc", foreign, wrong_salt):
            with self.subTest(token=token[:12]):
                self.assertEqual(self.undo(token).status_code, 400)
        self.car.refresh_from_db()
        self.assertIsNone(self.car.current_dealer)

    def test_token_is_void_once_the_car_has_moved_again(self):
        token = self.move_home()["undo_token"]
        self.assertEqual(self.post(str(self.open_dealer.pk), expected=self.home).status_code, 200)
        response = self.post(str(self.closed.pk), expected=str(self.open_dealer.pk), undo="1", undo_token=token)
        self.assertEqual(response.status_code, 400)
        self.car.refresh_from_db()
        self.assertEqual(self.car.current_dealer, self.open_dealer)
