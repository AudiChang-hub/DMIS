from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from sales.models import VehicleInventory, VehicleInventoryHistory
from sales.tests import test_order_lifecycle as lifecycle

TRANSFER = VehicleInventory.AcquisitionType.DEALER_TRANSFER
COMPANY = VehicleInventory.AcquisitionType.COMPANY


class InventoryAcquisitionTests(TestCase):
    setUp = lifecycle.OrderLifecycleTests.setUp

    def vehicle(self, tag, **extra):
        return VehicleInventory.objects.create(
            vehicle_model=self.model, color=self.color, engine_number=f"ACQ-{tag}",
            ownership_store=self.store, location_store=self.store, **extra,
        )

    def single_payload(self, **overrides):
        payload = {
            "vehicle_model": self.model.pk,
            "color": self.color.pk,
            "engine_number": "ACQ-SINGLE",
            "frame_number": "",
            "acquisition_type": COMPANY,
            "transfer_source_name": "",
            "current_dealer": "",
            "received_on": "2026-10-05",
            "manufactured_year_month": "2026/09",
            "condition_note": "",
            "condition_resolution": "",
            "resale_price": "",
        }
        payload.update(overrides)
        return payload

    def quick_payload(self, rows):
        payload = {
            "vehicles-TOTAL_FORMS": str(len(rows)),
            "vehicles-INITIAL_FORMS": "0",
            "vehicles-MIN_NUM_FORMS": "0",
            "vehicles-MAX_NUM_FORMS": "100",
        }
        for index, row in enumerate(rows):
            for field in ("vehicle_model", "color", "identifier", "received_on", "manufactured_year_month",
                          "condition_note", "acquisition_type", "transfer_source_name"):
                payload[f"vehicles-{index}-{field}"] = row.get(field, "")
        return payload

    def test_model_requires_source_for_transfer_and_clears_it_for_company(self):
        with self.assertRaises(ValidationError) as caught:
            self.vehicle("NO-SOURCE", acquisition_type=TRANSFER)
        self.assertIn("transfer_source_name", caught.exception.message_dict)
        company = self.vehicle("COMPANY", transfer_source_name="不該保留")
        self.assertEqual(company.acquisition_type, COMPANY)
        self.assertEqual(company.transfer_source_name, "")
        self.assertEqual(company.acquisition_label, "公司進車")
        transfer = self.vehicle("TRANSFER", acquisition_type=TRANSFER, transfer_source_name=" 大發機車 ")
        self.assertEqual(transfer.acquisition_label, "調車｜大發機車")

    def test_single_create_records_dealer_transfer(self):
        self.client.force_login(self.user)
        url = reverse("inventory_create")
        page = self.client.get(url)
        self.assertContains(page, 'id="transfer-source-options"')
        self.assertContains(page, '<option value="合作車行甲">')
        self.assertContains(page, "車行調車")

        response = self.client.post(url, self.single_payload(acquisition_type=TRANSFER))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "車行調車請填寫跟哪一家車行調車。")
        self.assertFalse(VehicleInventory.objects.filter(engine_number="ACQ-SINGLE").exists())

        response = self.client.post(url, self.single_payload(acquisition_type=TRANSFER, transfer_source_name="大發機車"))
        self.assertRedirects(response, reverse("inventory_list"), fetch_redirect_response=False)
        vehicle = VehicleInventory.objects.get(engine_number="ACQ-SINGLE")
        self.assertEqual((vehicle.acquisition_type, vehicle.transfer_source_name), (TRANSFER, "大發機車"))

    def test_quick_create_sets_source_per_row_and_defaults_to_company(self):
        self.client.force_login(self.user)
        base = {"vehicle_model": self.model.pk, "color": self.color.pk, "received_on": "2026-10-05"}
        missing = self.client.post(reverse("inventory_quick_create"), self.quick_payload([
            {**base, "identifier": "ACQ-Q1", "acquisition_type": TRANSFER},
        ]))
        self.assertContains(missing, "車行調車請填寫跟哪一家車行調車。")
        self.assertFalse(VehicleInventory.objects.filter(engine_number="ACQ-Q1").exists())

        response = self.client.post(reverse("inventory_quick_create"), self.quick_payload([
            {**base, "identifier": "ACQ-Q1", "acquisition_type": TRANSFER, "transfer_source_name": "大發機車"},
            {**base, "identifier": "ACQ-Q2", "acquisition_type": COMPANY, "transfer_source_name": "會被清除"},
            {**base, "identifier": "ACQ-Q3"},
        ]))
        self.assertRedirects(response, reverse("inventory_list"), fetch_redirect_response=False)
        rows = dict(
            (engine, (kind, source))
            for engine, kind, source in VehicleInventory.objects.filter(engine_number__startswith="ACQ-Q")
            .values_list("engine_number", "acquisition_type", "transfer_source_name")
        )
        self.assertEqual(rows, {
            "ACQ-Q1": (TRANSFER, "大發機車"),
            "ACQ-Q2": (COMPANY, ""),
            "ACQ-Q3": (COMPANY, ""),
        })

    def test_editing_source_writes_inventory_history(self):
        vehicle = self.vehicle("EDIT")
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("inventory_edit", args=[vehicle.pk]),
            self.single_payload(engine_number="ACQ-EDIT", acquisition_type=TRANSFER, transfer_source_name="大發機車"),
        )
        self.assertRedirects(response, reverse("inventory_list"), fetch_redirect_response=False)
        change = VehicleInventoryHistory.objects.filter(vehicle=vehicle).latest("pk").changes["acquisition"]
        self.assertEqual((change["before"], change["after"]), ("公司進車", "調車｜大發機車"))

    def test_inventory_list_shows_badge_filters_and_searches_by_source(self):
        transfer = self.vehicle("LIST-T", acquisition_type=TRANSFER, transfer_source_name="大發機車")
        company = self.vehicle("LIST-C")
        self.client.force_login(self.user)
        response = self.client.get(reverse("inventory_list"))
        self.assertContains(response, '<small class="inventory-acquisition" title="車行調車">調車｜大發機車</small>', html=True)
        self.assertEqual({v.pk for v in response.context["vehicles"]}, {transfer.pk, company.pk})
        filtered = self.client.get(reverse("inventory_list"), {"acquisition": TRANSFER})
        self.assertEqual([v.pk for v in filtered.context["vehicles"]], [transfer.pk])
        searched = self.client.get(reverse("inventory_list"), {"q": "大發"})
        self.assertEqual([v.pk for v in searched.context["vehicles"]], [transfer.pk])
