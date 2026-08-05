from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from openpyxl import Workbook

from sales.models import (
    LegacyImportBatch,
    LegacySalesSnapshot,
    SalesOrder,
    Store,
    VehicleInventory,
)
from sales.forms import LegacyImportUploadForm
from sales.services.legacy_import import build_import_preview, confirm_import, file_sha256


def workbook_bytes(kind="operations"):
    workbook = Workbook()
    if kind == "operations":
        sales = workbook.active
        sales.title = "銷貨"
        sales["C3"] = "車種型號"
        sales["D3"] = "識別號碼"
        sales["E3"] = "車主名稱"
        sales["G3"] = "收款價"
        sales["H3"] = "成本"
        sales["J3"] = "現金"
        sales["B4"] = "2026/08/01"
        sales["C4"] = "TEST125"
        sales["D4"] = " ab-123 "
        sales["E4"] = "舊欄姓名"
        sales["AT4"] = "正式車主"
        sales["F4"] = "白"
        sales["G4"] = 70000
        sales["H4"] = 60000
        sales["J4"] = 70000
        sales["AS4"] = "ABC-1234"
        sales["AW4"] = "A123456789"
        sales["AX4"] = "新北市測試路1號"
        sales["AY4"] = "0912345678"
        sales["CH4"] = "2026/07/30"
        inventory = workbook.create_sheet("進貨")
        for column, label in enumerate(("進貨日期", "車種型號", "車身號碼", "顏色", "尺碼", "數量", "單價", "總額", "月份", "出廠日期"), 1):
            inventory.cell(1, column, label)
        inventory.append(["2026/07/01", "TEST125", " AB-123 ", "白", "", 0, "", "", "", "2026/06"])
    else:
        dealer = workbook.active
        dealer.title = "車行"
        dealer.append(["", "", "", "", "", "", "", "月餅", "價格表", "容量"])
        dealer.append(["店名", "負責人", "電話一", "電話二", "手機", "傳真", "地址", "三陽", "台鈴", "排車容量", "備註"])
        dealer.append(["測試車行", "王先生", "02-1234", "", "0912", "", "新北市", "", "V", 5, "合作中"])
        platform = workbook.create_sheet("網路平台")
        platform.append(["平台", "聯絡人", "電話", "分機", "手機", "信箱"])
        platform.append(["測試平台", "李小姐", "02-5678", "123", "", "test@example.com"])
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


class LegacyImportTests(TestCase):
    def setUp(self):
        Store.objects.create(name="總店", code="MAIN")
        self.tempdir = TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.tempdir.name)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        self.tempdir.cleanup()

    def make_batch(self, kind):
        content = workbook_bytes(kind)
        upload = SimpleUploadedFile(f"{kind}.xlsx", content)
        digest = file_sha256(upload)
        return LegacyImportBatch.objects.create(
            import_type=kind,
            source_file=upload,
            original_filename=f"{kind}.xlsx",
            file_sha256=digest,
            file_size=len(content),
            uploaded_by="tester",
        )

    def test_upload_form_only_contains_type_and_file(self):
        self.assertEqual(list(LegacyImportUploadForm().fields), ["import_type", "source_file"])

    def test_operations_preview_and_confirm_preserves_historical_price(self):
        batch = self.make_batch(LegacyImportBatch.ImportType.OPERATIONS)
        summary = build_import_preview(batch)
        self.assertEqual(summary["source_rows"], 2)
        self.assertEqual(batch.rows.filter(sheet_name="銷貨").count(), 1)
        result = confirm_import(batch, "tester")
        self.assertEqual(result["created"], 2)
        order = SalesOrder.objects.get(owner_name="正式車主")
        self.assertEqual(order.vehicle_price, 0)
        self.assertEqual(order.allocated_vehicle.normalized_engine_number, "AB123")
        self.assertEqual(order.legacy_snapshot.historical_received_price, 70000)
        self.assertEqual(LegacySalesSnapshot.objects.count(), 1)
        self.assertEqual(VehicleInventory.objects.get().status, VehicleInventory.Status.SOLD)

    def test_channel_preview_groups_source_and_contact(self):
        batch = self.make_batch(LegacyImportBatch.ImportType.CHANNELS)
        summary = build_import_preview(batch)
        self.assertEqual(summary["source_rows"], 2)
        result = confirm_import(batch, "tester")
        self.assertEqual(result["created"], 2)
        self.assertEqual(batch.rows.filter(committed_model="SalesSource").count(), 2)

    def test_same_batch_cannot_be_confirmed_twice(self):
        batch = self.make_batch(LegacyImportBatch.ImportType.CHANNELS)
        build_import_preview(batch)
        confirm_import(batch, "tester")
        with self.assertRaises(ValueError):
            confirm_import(batch, "tester")
