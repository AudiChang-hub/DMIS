"""T-229：車輛庫存畫面顯示「名稱 色碼」；進車選既有車色帶出色碼，沒遇過的新顏色不帶色碼。"""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.forms import QuickInventoryEntryForm, VehicleInventoryForm
from sales.models import Store, VehicleColor, VehicleInventory, VehicleModel
from sales.services.legacy_import import _color_for_model


class InventoryColorCodeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", password="Test-Only-123")
        cls.store = Store.objects.create(name="總店", code="MAIN")
        cls.model = VehicleModel.objects.create(
            brand="SUZUKI", name="SUI 125", model_number="UC125", energy_type="gas",
            model_year=2026, model_code="drum", displacement_cc=125,
        )
        cls.other_model = VehicleModel.objects.create(
            brand="SUZUKI", name="Saluto 125", model_number="UC125S", energy_type="gas",
            model_year=2026, model_code="disc", displacement_cc=125,
        )
        cls.coded = VehicleColor.objects.create(vehicle_model=cls.model, name="帕瑪森白", code="W17")
        cls.plain = VehicleColor.objects.create(vehicle_model=cls.model, name="鈦灰")
        cls.white = VehicleColor.objects.create(vehicle_model=cls.model, name="白", code="W13")
        cls.other_white = VehicleColor.objects.create(vehicle_model=cls.other_model, name="白", code="RB5")

    def setUp(self):
        self.client.force_login(self.admin)

    def vehicle(self, color, tag, **extra):
        return VehicleInventory.objects.create(
            vehicle_model=color.vehicle_model, color=color, engine_number=f"T229-{tag}",
            ownership_store=self.store, location_store=self.store, received_on=date(2026, 11, 18), **extra,
        )

    def test_inventory_list_row_and_color_filter_show_code(self):
        self.vehicle(self.coded, "A")
        self.vehicle(self.plain, "B")
        response = self.client.get(reverse("inventory_list"))
        self.assertContains(response, "<span>帕瑪森白 W17</span>", html=True)
        self.assertContains(response, '<option value="帕瑪森白">帕瑪森白 W17（1）</option>', html=True)
        # 沒有色碼的只顯示名稱。
        self.assertContains(response, '<option value="鈦灰">鈦灰（1）</option>', html=True)

    def test_inventory_color_filter_lists_codes_of_same_name_colors(self):
        self.vehicle(self.white, "W1")
        self.vehicle(self.other_white, "W2")
        response = self.client.get(reverse("inventory_list"))
        self.assertContains(response, '<option value="白">白 RB5／W13（2）</option>', html=True)
        # 篩選仍以名稱合併，兩個車型的「白」都篩得到。
        filtered = self.client.get(reverse("inventory_list"), {"color": "白"})
        self.assertContains(filtered, "T229-W1")
        self.assertContains(filtered, "T229-W2")
        self.assertContains(filtered, '<option value="白" selected>白 RB5／W13（2）</option>', html=True)

    def test_receipt_list_filter_shows_code_and_still_filters_by_name(self):
        self.vehicle(self.coded, "R1")
        self.vehicle(self.plain, "R2")
        response = self.client.get(reverse("inventory_receipt_list"))
        self.assertContains(response, "<span>帕瑪森白 W17</span>", html=True)
        self.assertContains(response, '<option value="帕瑪森白">帕瑪森白 W17</option>', html=True)
        self.assertContains(response, '<option value="鈦灰">鈦灰</option>', html=True)
        filtered = self.client.get(reverse("inventory_receipt_list"), {"color": "帕瑪森白"})
        self.assertContains(filtered, "T229-R1")
        self.assertNotContains(filtered, "T229-R2")
        self.assertContains(filtered, '<option value="帕瑪森白" selected>帕瑪森白 W17</option>', html=True)

    def test_single_intake_existing_color_shows_code(self):
        form = VehicleInventoryForm(data={"vehicle_model": str(self.model.pk)})
        labels = {label for _, label in form.fields["color"].choices}
        self.assertIn("帕瑪森白 W17", labels)
        self.assertIn("鈦灰", labels)
        # 換車型時前端從 /api/colors/ 載入，同樣帶出色碼。
        api = self.client.get(reverse("vehicle_colors"), {"model": self.model.pk}).json()["results"]
        self.assertIn({"id": self.coded.pk, "name": "帕瑪森白 W17"}, api)

    def test_quick_intake_existing_color_shows_code(self):
        form = QuickInventoryEntryForm(data={"vehicles-0-vehicle_model": str(self.model.pk)}, prefix="vehicles-0")
        labels = {label for _, label in form.fields["color"].choices}
        self.assertIn("帕瑪森白 W17", labels)
        self.assertIn("鈦灰", labels)

    def test_inventory_edit_shows_selected_color_code(self):
        vehicle = self.vehicle(self.coded, "E1")
        response = self.client.get(reverse("inventory_edit", args=[vehicle.pk]))
        self.assertContains(response, f'<option value="{self.coded.pk}" selected>帕瑪森白 W17</option>', html=True)

    def test_excel_intake_reuses_existing_color_code_and_new_color_has_none(self):
        self.assertEqual(_color_for_model(self.model, "帕瑪森白"), self.coded)
        new_color = _color_for_model(self.model, "極光綠")
        self.assertEqual(new_color.code, "")
        self.assertEqual(new_color.label, "極光綠")
        self.assertFalse(new_color.active)
