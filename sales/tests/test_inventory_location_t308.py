"""T-308 B：庫存列表的「實際位置」直接下拉改，選了就存（使用者 2026-11-24 選 B）。

只改車放在哪裡：不改狀態、去向，不產生調車簽收；每次改動記一筆「調度車輛」歷程。
選項和編輯表單共用（sales/services/inventory_location.py）。
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.forms import VehicleInventoryForm
from sales.models import (
    SalesSource,
    Store,
    VehicleColor,
    VehicleInventory,
    VehicleInventoryHistory,
    VehicleModel,
    VehicleTransferSignoff,
)

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


class InventoryLocationTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.root = users.create_superuser("admin", password="Local-t308-553!")
        self.client.force_login(self.root)
        self.yusheng = Store.objects.create(name="馭盛", code="HQ")
        self.yongzhan = Store.objects.create(name="永湛", code="YZ")
        self.dealer = SalesSource.objects.create(name="示範車行甲", source_type=SalesSource.SourceType.DEALER)
        self.other_dealer = SalesSource.objects.create(name="示範車行乙", source_type=SalesSource.SourceType.DEALER)
        self.closed_dealer = SalesSource.objects.create(
            name="已停用車行", source_type=SalesSource.SourceType.DEALER, active=False,
        )
        self.model = VehicleModel.objects.create(brand="SYM", name="JET SL 125", model_number="T308")
        self.color = VehicleColor.objects.create(vehicle_model=self.model, name="消光黑")
        self.car = self.make_car("T3080001")

    def make_car(self, frame, **fields):
        fields.setdefault("location_store", self.yusheng)
        return VehicleInventory.objects.create(
            vehicle_model=self.model, color=self.color, frame_number=frame, ownership_store=self.yusheng, **fields,
        )

    def move(self, location, car=None, **extra):
        car = car or self.car
        return self.client.post(reverse("inventory_location", args=[car.pk]), {"location": location, **extra}, **AJAX)

    def test_moving_to_dealer_keeps_store_status_and_disposition_and_logs_one_transfer(self):
        response = self.move(str(self.dealer.pk), expected=f"home-{self.yusheng.pk}")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual((payload["ok"], payload["changed"]), (True, True))
        self.assertEqual((payload["value"], payload["label"]), (str(self.dealer.pk), "示範車行甲"))
        self.assertEqual((payload["previous_value"], payload["previous_label"]), (f"home-{self.yusheng.pk}", "本店：馭盛"))
        self.assertEqual(payload["message"], "T3080001 已改放到 示範車行甲")
        self.car.refresh_from_db()
        self.assertEqual((self.car.current_dealer, self.car.location_store), (self.dealer, self.yusheng))
        self.assertEqual(self.car.status, VehicleInventory.Status.AVAILABLE)
        self.assertEqual(self.car.disposition, "")
        self.assertFalse(VehicleTransferSignoff.objects.exists(), "改位置不產生調車簽收")
        history = self.car.history_entries.get()
        self.assertEqual(history.event_type, VehicleInventoryHistory.EventType.TRANSFERRED)
        self.assertEqual(history.reason, "改位置")
        self.assertEqual((history.from_location_label, history.to_location_label), ("本店", "示範車行甲"))
        self.assertEqual(history.changes["current_dealer"], {"label": "實際位置", "before": "本店", "after": "示範車行甲"})
        self.assertEqual(history.actor_name, "admin")

    def test_moving_to_other_home_store_clears_dealer_and_changes_store(self):
        self.car.current_dealer = self.dealer
        self.car.save()
        self.move(f"home-{self.yongzhan.pk}")
        self.car.refresh_from_db()
        self.assertEqual((self.car.current_dealer, self.car.location_store), (None, self.yongzhan))
        self.assertEqual(self.car.ownership_store, self.yusheng, "只改實際存放門市，不改歸屬門市")
        history = self.car.history_entries.get()
        self.assertEqual((history.from_location_label, history.to_location_label), ("示範車行甲", "本店：永湛"))

    def test_same_location_is_skipped_without_history(self):
        payload = self.move(f"home-{self.yusheng.pk}").json()
        self.assertEqual((payload["ok"], payload["changed"]), (True, False))
        self.assertFalse(self.car.history_entries.exists())

    def test_undo_moves_back_and_logs_its_own_entry(self):
        self.move(str(self.dealer.pk))
        payload = self.move(f"home-{self.yusheng.pk}", expected=str(self.dealer.pk), undo="1").json()
        self.assertEqual((payload["ok"], payload["changed"], payload["label"]), (True, True, "本店：馭盛"))
        self.car.refresh_from_db()
        self.assertEqual((self.car.current_dealer, self.car.location_store), (None, self.yusheng))
        self.assertEqual(
            list(self.car.history_entries.order_by("pk").values_list("reason", flat=True)), ["改位置", "改位置（復原）"],
        )

    def test_stale_expected_location_is_rejected_with_current_value(self):
        self.car.current_dealer = self.other_dealer
        self.car.save()
        response = self.move(str(self.dealer.pk), expected=f"home-{self.yusheng.pk}")
        self.assertEqual(response.status_code, 409)
        payload = response.json()
        self.assertEqual((payload["ok"], payload["value"], payload["label"]), (False, str(self.other_dealer.pk), "示範車行乙"))
        self.car.refresh_from_db()
        self.assertEqual(self.car.current_dealer, self.other_dealer)
        self.assertFalse(self.car.history_entries.exists())

    def test_reserved_car_can_move(self):
        VehicleInventory.objects.filter(pk=self.car.pk).update(status=VehicleInventory.Status.RESERVED)
        self.assertEqual(self.move(str(self.dealer.pk)).status_code, 200)
        self.car.refresh_from_db()
        self.assertEqual((self.car.current_dealer, self.car.status), (self.dealer, VehicleInventory.Status.RESERVED))

    def test_delivered_sold_and_transferred_out_cars_are_rejected(self):
        for status in (
            VehicleInventory.Status.DELIVERED, VehicleInventory.Status.SOLD, VehicleInventory.Status.TRANSFERRED_OUT,
        ):
            with self.subTest(status=status):
                VehicleInventory.objects.filter(pk=self.car.pk).update(status=status)
                response = self.move(str(self.dealer.pk))
                self.assertEqual(response.status_code, 409)
                self.assertIn("不能改位置", response.json()["message"])
                self.car.refresh_from_db()
                self.assertIsNone(self.car.current_dealer)
        self.assertFalse(self.car.history_entries.exists())

    def test_unknown_or_inactive_location_is_rejected(self):
        for value in ("", "home-999999", "999999", "abc", str(self.closed_dealer.pk)):
            with self.subTest(value=value):
                self.assertEqual(self.move(value).status_code, 400)
        self.car.refresh_from_db()
        self.assertIsNone(self.car.current_dealer)

    def test_car_already_at_inactive_dealer_keeps_it_as_option(self):
        self.car.current_dealer = self.closed_dealer
        self.car.save()
        payload = self.move(str(self.closed_dealer.pk)).json()
        self.assertEqual((payload["ok"], payload["changed"]), (True, False))
        html = self.client.get(reverse("inventory_list")).content.decode()
        self.assertIn(f'<option value="{self.closed_dealer.pk}" selected>已停用車行</option>', html)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(reverse("inventory_location", args=[self.car.pk])).status_code, 405)

    def test_plain_form_post_redirects_back_with_message(self):
        response = self.client.post(
            reverse("inventory_location", args=[self.car.pk]),
            {"location": str(self.dealer.pk), "next": reverse("inventory_list") + "?sort=brand"},
        )
        self.assertRedirects(response, reverse("inventory_list") + "?sort=brand", fetch_redirect_response=False)
        self.car.refresh_from_db()
        self.assertEqual(self.car.current_dealer, self.dealer)

    def test_list_rows_carry_only_current_option_and_page_shares_one_option_list(self):
        self.make_car("T3080002", current_dealer=self.dealer)
        self.make_car("T3080003", location_store=self.yongzhan)
        html = self.client.get(reverse("inventory_list")).content.decode()
        self.assertEqual(html.count('class="inventory-location__select"'), 3)
        self.assertIn(f'<option value="home-{self.yusheng.pk}" selected>本店：馭盛</option>', html)
        self.assertIn(f'<option value="{self.dealer.pk}" selected>示範車行甲</option>', html)
        self.assertIn(f'<option value="home-{self.yongzhan.pk}" selected>本店：永湛</option>', html)
        template = html[html.index('<template id="inventory-location-options"'):html.index("</template>")]
        self.assertEqual(html.count('id="inventory-location-options"'), 1)
        self.assertIn(
            f'<optgroup label="本店"><option value="home-{self.yusheng.pk}">本店：馭盛</option>'
            f'<option value="home-{self.yongzhan.pk}">本店：永湛</option></optgroup>', template,
        )
        self.assertIn(
            f'<optgroup label="車行"><option value="{self.other_dealer.pk}">示範車行乙</option>'
            f'<option value="{self.dealer.pk}">示範車行甲</option></optgroup>', template,
        )
        self.assertNotIn("已停用車行", template)
        self.assertIn("inventory-location.js", html)
        self.assertIn("請用", html)

    def test_list_options_match_edit_form_choices(self):
        from sales.services.inventory_location import LocationOptions
        options = LocationOptions()
        form = VehicleInventoryForm(instance=self.car)
        self.assertEqual(options.home_choices + options.dealer_choices, list(form.fields["current_dealer"].choices))

    def test_other_tabs_keep_plain_text_location(self):
        VehicleInventory.objects.filter(pk=self.car.pk).update(status=VehicleInventory.Status.INACTIVE)
        html = self.client.get(reverse("inventory_list"), {"scope": "history"}).content.decode()
        self.assertNotIn("inventory-location__select", html)
        self.assertNotIn("inventory-location-options", html)


class InventoryLocationPermissionTests(TestCase):
    def setUp(self):
        self.store = Store.objects.create(name="馭盛", code="HQ")
        self.dealer = SalesSource.objects.create(name="示範車行甲", source_type=SalesSource.SourceType.DEALER)
        model = VehicleModel.objects.create(brand="SYM", name="JET SL 125", model_number="T308P")
        color = VehicleColor.objects.create(vehicle_model=model, name="消光黑")
        self.car = VehicleInventory.objects.create(
            vehicle_model=model, color=color, frame_number="T308P0001", ownership_store=self.store, location_store=self.store,
        )
        self.user = get_user_model().objects.create_user("viewer", password="Local-t308-553!")
        UserAccessState.objects.create(user=self.user, configured=True)
        self.grant = ScreenAccessGrant.objects.create(user=self.user, screen_key="inventory", view=True)
        self.client.force_login(self.user)

    def test_view_only_user_gets_403_and_sees_text_without_select(self):
        response = self.client.post(reverse("inventory_location", args=[self.car.pk]), {"location": str(self.dealer.pk)}, **AJAX)
        self.assertEqual(response.status_code, 403)
        self.car.refresh_from_db()
        self.assertIsNone(self.car.current_dealer)
        html = self.client.get(reverse("inventory_list")).content.decode()
        self.assertNotIn("inventory-location__select", html)
        self.assertNotIn("inventory-location-options", html)
        self.assertIn("<strong>本店</strong>", html)

    def test_operate_user_can_move(self):
        self.grant.operate = True
        self.grant.save()
        self.assertIn("inventory-location__select", self.client.get(reverse("inventory_list")).content.decode())
        response = self.client.post(reverse("inventory_location", args=[self.car.pk]), {"location": str(self.dealer.pk)}, **AJAX)
        self.assertEqual(response.status_code, 200)
        self.car.refresh_from_db()
        self.assertEqual(self.car.current_dealer, self.dealer)


class InventoryFormLocationUnchangedTests(TestCase):
    """抽出共用選項後，編輯表單的實際位置選單與存法不變。"""

    def setUp(self):
        self.yusheng = Store.objects.create(name="馭盛", code="HQ")
        self.yongzhan = Store.objects.create(name="永湛", code="YZ")
        self.b = SalesSource.objects.create(name="B 車行", source_type=SalesSource.SourceType.DEALER)
        self.a = SalesSource.objects.create(name="A 車行", source_type=SalesSource.SourceType.DEALER)
        self.closed = SalesSource.objects.create(name="C 停用", source_type=SalesSource.SourceType.DEALER, active=False)
        SalesSource.objects.create(name="店家", source_type=SalesSource.SourceType.STORE)
        model = VehicleModel.objects.create(brand="SYM", name="JET SL 125", model_number="T308F")
        self.color = VehicleColor.objects.create(vehicle_model=model, name="消光黑")
        self.model = model

    def car(self, **fields):
        return VehicleInventory.objects.create(
            vehicle_model=self.model, color=self.color, frame_number=f"T308F{VehicleInventory.objects.count()}",
            ownership_store=self.yusheng, location_store=fields.pop("location_store", self.yusheng), **fields,
        )

    def test_choices_initial_and_inactive_current_dealer(self):
        form = VehicleInventoryForm(instance=self.car(location_store=self.yongzhan))
        field = form.fields["current_dealer"]
        self.assertEqual(list(field.choices), [
            (f"home-{self.yusheng.pk}", "本店：馭盛"), (f"home-{self.yongzhan.pk}", "本店：永湛"),
            (str(self.a.pk), "A 車行"), (str(self.b.pk), "B 車行"),
        ])
        self.assertEqual(form.initial["current_dealer"], f"home-{self.yongzhan.pk}")
        closed_form = VehicleInventoryForm(instance=self.car(current_dealer=self.closed))
        self.assertEqual([value for value, _ in closed_form.fields["current_dealer"].choices][-1], str(self.closed.pk))
        self.assertEqual(closed_form.initial["current_dealer"], str(self.closed.pk))
        new_form = VehicleInventoryForm()
        self.assertNotIn(str(self.closed.pk), [value for value, _ in new_form.fields["current_dealer"].choices])
        self.assertEqual(new_form.initial["current_dealer"], f"home-{self.yusheng.pk}")

    def test_without_home_stores_form_keeps_legacy_dealer_select(self):
        self.yusheng.name, self.yongzhan.name = "總店", "二店"
        self.yusheng.save()
        self.yongzhan.save()
        form = VehicleInventoryForm(instance=self.car(current_dealer=self.closed))
        field = form.fields["current_dealer"]
        self.assertEqual(field.empty_label, "本店")
        self.assertEqual(list(field.queryset), [self.a, self.b, self.closed])
