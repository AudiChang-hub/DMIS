"""1.61.0：Excel 進貨數量 0＝已售出、M 欄（存放／調車）判讀，以及庫存去向篩選。"""
from datetime import date
from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from sales.models import (
    LegacyImportBatch,
    SalesSource,
    Store,
    VehicleColor,
    VehicleInventory,
    VehicleModel,
)
from sales.services.inventory_location_note import (
    DEALER_PICKUP,
    LOCATION,
    TRANSFER_OUT,
    parse,
)
from sales.services.legacy_import import (
    build_import_preview,
    confirm_import,
    file_sha256,
)

RECEIVED = date(2026, 3, 1)


class LocationNoteParseTests(SimpleTestCase):
    def test_dealer_name_only_is_location(self):
        result = parse("昌勝", RECEIVED)
        self.assertEqual((result["kind"], result["name"], result["store"]), (LOCATION, "昌勝", False))

    def test_dealer_with_parenthesis_keeps_note(self):
        result = parse("昌勝(已配電)", RECEIVED)
        self.assertEqual((result["kind"], result["name"], result["note"]), (LOCATION, "昌勝", "已配電"))

    def test_transfer_variants(self):
        for text in ("昌勝調走", "昌勝調", "昌勝已調走"):
            with self.subTest(text=text):
                result = parse(text, RECEIVED)
                self.assertEqual((result["kind"], result["name"]), (TRANSFER_OUT, "昌勝"))

    def test_transfer_with_month_day_infers_year_from_received_date(self):
        self.assertEqual(parse("4/12 昌勝調走", RECEIVED)["on"], date(2026, 4, 12))
        # 早於進貨日的月／日視為隔年。
        self.assertEqual(parse("1/5 昌勝調", RECEIVED)["on"], date(2027, 1, 5))

    def test_transfer_back_to_factory(self):
        result = parse("調回工廠", RECEIVED)
        self.assertEqual((result["kind"], result["name"]), (TRANSFER_OUT, "工廠"))

    def test_dealer_pickup(self):
        result = parse("5/2 大發領", RECEIVED)
        self.assertEqual((result["kind"], result["name"], result["on"]), (DEALER_PICKUP, "大發", date(2026, 5, 2)))

    def test_store_words_and_free_text(self):
        self.assertTrue(parse("馭盛", RECEIVED)["store"])
        self.assertTrue(parse("公司", RECEIVED)["store"])
        store_pickup = parse("馭盛領", RECEIVED)
        self.assertEqual((store_pickup["kind"], store_pickup["store"], store_pickup["note"]), (LOCATION, True, "馭盛領"))
        result = parse("員購車", RECEIVED)
        self.assertEqual((result["kind"], result["store"], result["raw"]), (LOCATION, False, "員購車"))

    def test_blank(self):
        self.assertEqual(parse("  ", RECEIVED)["kind"], "")


def inventory_workbook(rows, location_header=None):
    """rows：(車身號碼, 數量, M 欄文字)。M 欄預設無表頭，與正式 Excel 相同。"""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "進貨"
    labels = ["進貨日期", "車種型號", "車身號碼", "顏色", "尺碼", "數量", "單價", "總額", "月份", "出廠日期", None, None, location_header]
    for column, label in enumerate(labels, 1):
        if label:
            sheet.cell(1, column, label)
    for number, quantity, note in rows:
        sheet.append(["2026/03/01", "TEST125", number, "白", "", quantity, "", "", "", "2026/02", None, None, note])
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


class InventoryImportDispositionTests(TestCase):
    def setUp(self):
        Store.objects.create(name="總店", code="MAIN")
        self.changsheng = SalesSource.objects.create(
            name="昌勝", source_type=SalesSource.SourceType.DEALER, active=True
        )
        self.tempdir = TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.tempdir.name)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        self.tempdir.cleanup()

    def run_import(self, content):
        upload = SimpleUploadedFile("inventory.xlsx", content)
        batch = LegacyImportBatch.objects.create(
            import_type=LegacyImportBatch.ImportType.OPERATIONS,
            source_file=upload,
            original_filename="inventory.xlsx",
            file_sha256=file_sha256(upload),
            file_size=len(content),
            uploaded_by="tester",
        )
        build_import_preview(batch, sheets=["進貨"])
        confirm_import(batch, "tester")
        return {vehicle.identifier: vehicle for vehicle in VehicleInventory.objects.select_related("current_dealer", "disposition_dealer")}

    def test_quantity_and_unlabeled_m_column(self):
        vehicles = self.run_import(inventory_workbook([
            ("FR001", 1, "昌勝"),
            ("FR002", 0, "4/12 昌勝調走"),
            ("FR003", 0, "大發領"),
            ("FR004", 0, "員購車"),
            ("FR005", 1, "馭盛"),
            ("FR006", 0, "昌勝"),
            ("FR007", 0, ""),
            ("FR008", 1, "昌勝調走"),
        ]))
        in_stock = vehicles["FR001"]
        self.assertEqual(in_stock.status, VehicleInventory.Status.AVAILABLE)
        self.assertEqual(in_stock.current_dealer, self.changsheng)
        self.assertEqual(in_stock.disposition, "")

        transferred = vehicles["FR002"]
        # 調出不是售出：已調出，不算庫存但保留紀錄。
        self.assertEqual(transferred.status, VehicleInventory.Status.TRANSFERRED_OUT)
        self.assertEqual(transferred.disposition, VehicleInventory.Disposition.TRANSFER_OUT)
        self.assertEqual(transferred.disposition_dealer, self.changsheng)
        self.assertEqual(transferred.disposition_on, date(2026, 4, 12))

        picked_up = vehicles["FR003"]
        self.assertEqual(picked_up.status, VehicleInventory.Status.SOLD)
        self.assertEqual(picked_up.disposition, VehicleInventory.Disposition.DEALER_PICKUP)
        self.assertIsNone(picked_up.disposition_dealer)  # 車行主檔沒有「大發」：保留原文
        self.assertEqual(picked_up.disposition_dealer_name, "大發")
        self.assertEqual(picked_up.disposition_target_label, "大發")

        self.assertEqual(vehicles["FR004"].note, "員購車")
        self.assertEqual(vehicles["FR004"].disposition, "")
        self.assertIsNone(vehicles["FR005"].current_dealer)
        self.assertEqual(vehicles["FR005"].note, "")
        # 已售出的車不改實際位置，只記曾放在哪間車行。
        self.assertIsNone(vehicles["FR006"].current_dealer)
        self.assertEqual(vehicles["FR006"].note, "曾放在 昌勝")
        self.assertEqual(vehicles["FR007"].status, VehicleInventory.Status.SOLD)
        self.assertEqual(vehicles["FR007"].note, "")
        # 數量 1 卻寫調出：以數量為準仍是庫存，原文只存備註。
        self.assertEqual(vehicles["FR008"].status, VehicleInventory.Status.AVAILABLE)
        self.assertEqual(vehicles["FR008"].disposition, "")
        self.assertEqual(vehicles["FR008"].note, "昌勝調走")

    def test_m_column_with_named_header_is_read(self):
        vehicles = self.run_import(inventory_workbook([("FR010", 0, "昌勝調")], location_header="存放／調車"))
        self.assertEqual(vehicles["FR010"].disposition, VehicleInventory.Disposition.TRANSFER_OUT)

    def test_m_column_with_unrelated_header_is_ignored(self):
        vehicles = self.run_import(inventory_workbook([("FR011", 0, "昌勝調")], location_header="其他"))
        self.assertEqual(vehicles["FR011"].disposition, "")
        self.assertEqual(vehicles["FR011"].note, "")


class InventoryDispositionListTests(TestCase):
    def setUp(self):
        self.store = Store.objects.create(name="總店", code="MAIN")
        self.user = get_user_model().objects.create_user(username="stock", password="test-pass")
        self.client.force_login(self.user)
        self.model = VehicleModel.objects.create(brand="SYM", name="測試車", model_number="TEST125")
        self.color = VehicleColor.objects.create(vehicle_model=self.model, name="白")
        self.dealer_a = SalesSource.objects.create(name="昌勝", source_type=SalesSource.SourceType.DEALER, active=True)
        self.dealer_b = SalesSource.objects.create(name="大發", source_type=SalesSource.SourceType.DEALER, active=True)

    def vehicle(self, frame, **fields):
        fields.setdefault("status", VehicleInventory.Status.SOLD)
        return VehicleInventory.objects.create(
            vehicle_model=self.model, color=self.color, frame_number=frame,
            ownership_store=self.store, location_store=self.store, **fields,
        )

    def test_sold_scope_filters_by_disposition_and_dealer(self):
        to_a = self.vehicle("FR-A", status=VehicleInventory.Status.TRANSFERRED_OUT, disposition="transfer_out", disposition_dealer=self.dealer_a,
                            disposition_dealer_name="昌勝", disposition_on=date(2026, 4, 12))
        to_b = self.vehicle("FR-B", disposition="transfer_out", disposition_dealer=self.dealer_b,
                            disposition_dealer_name="大發")
        pickup = self.vehicle("FR-C", disposition="dealer_pickup", disposition_dealer_name="外縣市車行")
        plain = self.vehicle("FR-D", note="員購車")
        url = reverse("inventory_list")

        response = self.client.get(url, {"scope": "sold"})
        self.assertEqual(set(response.context["vehicles"]), {to_a, to_b, pickup, plain})
        self.assertContains(response, "已售出／調出共 4 台")
        self.assertContains(response, "2026/04/12")
        self.assertContains(response, "外縣市車行")
        self.assertContains(response, "備註：員購車")

        response = self.client.get(url, {"scope": "sold", "disposition": "transfer_out"})
        self.assertEqual(set(response.context["vehicles"]), {to_a, to_b})
        response = self.client.get(url, {"scope": "sold", "disposition_dealer": self.dealer_a.pk})
        self.assertEqual(list(response.context["vehicles"]), [to_a])
        response = self.client.get(url, {"scope": "sold", "status": "transferred_out"})
        self.assertEqual(list(response.context["vehicles"]), [to_a])
        self.assertContains(response, "已調出")
        self.assertNotIn(to_a, list(self.client.get(url).context["vehicles"]))
        response = self.client.get(url, {"scope": "sold", "disposition": "none"})
        self.assertEqual(list(response.context["vehicles"]), [plain])
        response = self.client.get(url, {"scope": "sold", "q": "外縣市"})
        self.assertEqual(list(response.context["vehicles"]), [pickup])

    def test_current_scope_shows_note_and_hides_disposition_filters(self):
        self.vehicle("FR-E", status=VehicleInventory.Status.AVAILABLE, note="無電瓶")
        response = self.client.get(reverse("inventory_list"))
        self.assertContains(response, "備註：無電瓶")
        self.assertNotContains(response, 'name="disposition"')

    def test_edit_form_records_disposition_in_history(self):
        vehicle = self.vehicle("FR-F")
        response = self.client.post(reverse("inventory_edit", args=[vehicle.pk]), {
            "acquisition_type": "company",
            "condition_note": "",
            "condition_resolution": "",
            "disposition": "transfer_out",
            "disposition_dealer": self.dealer_b.pk,
            "disposition_dealer_name": "",
            "disposition_on": "2026-10-10",
            "note": "業務帶走",
        })
        self.assertEqual(response.status_code, 302, getattr(response, "context", {}) and response.context["form"].errors)
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.disposition_dealer, self.dealer_b)
        self.assertEqual(vehicle.disposition_dealer_name, "大發")
        self.assertEqual(vehicle.note, "業務帶走")
        changes = vehicle.history_entries.get().changes
        self.assertIn("調出 大發 2026-10-10", changes["disposition"]["after"])

    def test_disposition_details_require_disposition(self):
        vehicle = self.vehicle("FR-G")
        response = self.client.post(reverse("inventory_edit", args=[vehicle.pk]), {
            "acquisition_type": "company",
            "disposition": "",
            "disposition_dealer": self.dealer_a.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("disposition", response.context["form"].errors)
