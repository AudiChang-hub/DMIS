from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook, load_workbook

from sales.models import (
    LegacyImportBatch,
    LegacyImportCorrection,
    LegacySalesSnapshot,
    SalesOrder,
    Store,
    VehicleInventory,
)
from sales.forms import LegacyImportRowCorrectionForm, LegacyImportUploadForm
from sales.services.legacy_import import (
    apply_import_row_decision,
    build_import_preview,
    confirm_import,
    file_sha256,
)


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


def conflict_workbook_bytes():
    workbook = load_workbook(BytesIO(workbook_bytes()))
    inventory = workbook["進貨"]
    inventory.append(["2026/07/02", "TEST125", "AB 123", "黑", "", 1, "", "", "", "2026/07"])
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


class LegacyImportTests(TestCase):
    def setUp(self):
        Store.objects.create(name="總店", code="MAIN")
        self.user = get_user_model().objects.create_user(username="importer", password="test-pass")
        self.client.force_login(self.user)
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

    def make_conflict_batch(self):
        content = conflict_workbook_bytes()
        upload = SimpleUploadedFile("conflicts.xlsx", content)
        digest = file_sha256(upload)
        return LegacyImportBatch.objects.create(
            import_type=LegacyImportBatch.ImportType.OPERATIONS,
            source_file=upload,
            original_filename="conflicts.xlsx",
            file_sha256=digest,
            file_size=len(content),
            uploaded_by="tester",
        )

    def test_upload_form_only_contains_type_and_file(self):
        self.assertEqual(list(LegacyImportUploadForm().fields), ["import_type", "source_file"])

    def test_invalid_row_can_be_excluded_without_filling_required_import_fields(self):
        batch = self.make_batch(LegacyImportBatch.ImportType.OPERATIONS)
        build_import_preview(batch)
        row = batch.rows.get(sheet_name="進貨")
        form = LegacyImportRowCorrectionForm(
            {"decision": "exclude", "reason": "來源列無法確認，先不匯入"},
            row=row,
        )
        self.assertTrue(form.is_valid(), form.errors)

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

    def test_unresolved_conflict_blocks_confirm(self):
        batch = self.make_conflict_batch()
        summary = build_import_preview(batch)
        self.assertEqual(summary["counts"]["conflict"], 2)
        with self.assertRaisesMessage(ValueError, "尚有 2 筆衝突或錯誤資料"):
            confirm_import(batch, "tester")
        self.assertFalse(SalesOrder.objects.exists())

    def test_correcting_identifier_revalidates_entire_batch_and_keeps_audit(self):
        batch = self.make_conflict_batch()
        build_import_preview(batch)
        row = batch.rows.filter(sheet_name="進貨").order_by("source_row").last()
        summary = apply_import_row_decision(
            row,
            {"identifier_raw": "AB-124"},
            LegacyImportCorrection.Decision.CORRECT,
            "第二筆識別號碼輸入錯誤",
            "tester",
        )
        row.refresh_from_db()
        self.assertEqual(summary["counts"]["conflict"], 0)
        self.assertEqual(row.mapped_data["identifier"], "AB124")
        self.assertTrue(row.manually_corrected)
        self.assertEqual(row.corrections.get().reason, "第二筆識別號碼輸入錯誤")

    def test_excluding_duplicate_resolves_conflict_without_changing_source(self):
        batch = self.make_conflict_batch()
        build_import_preview(batch)
        row = batch.rows.filter(sheet_name="進貨").order_by("source_row").last()
        original_raw = dict(row.raw_data)
        summary = apply_import_row_decision(
            row,
            {},
            LegacyImportCorrection.Decision.EXCLUDE,
            "Excel 重複列",
            "tester",
        )
        row.refresh_from_db()
        self.assertEqual(summary["counts"]["conflict"], 0)
        self.assertEqual(summary["counts"]["exclude"], 1)
        self.assertEqual(row.raw_data, original_raw)
        result = confirm_import(batch, "tester")
        self.assertEqual(result["excluded"], 1)

    def test_conflict_workspace_renders_and_row_can_be_corrected_in_browser_flow(self):
        batch = self.make_conflict_batch()
        build_import_preview(batch)
        conflict_url = reverse("legacy_import_detail", args=[batch.pk]) + "?action=conflict"
        response = self.client.get(conflict_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "重複資料比較")
        self.assertContains(response, "2 筆使用相同識別號碼")
        row = batch.rows.filter(sheet_name="進貨").order_by("source_row").last()
        edit_response = self.client.get(conflict_url + f"&edit={row.pk}")
        self.assertEqual(edit_response.status_code, 200)
        self.assertContains(edit_response, "修正或排除此列")
        post_response = self.client.post(
            reverse("legacy_import_row_decide", args=[batch.pk, row.pk]),
            {
                "decision": "correct",
                "received_on": "2026-07-02",
                "model_number": "TEST125",
                "identifier_raw": "AB-124",
                "color": "黑",
                "quantity": "1",
                "manufactured_year_month": "2026/07",
                "reason": "識別號碼更正",
            },
        )
        self.assertEqual(post_response.status_code, 302)
        batch.refresh_from_db()
        self.assertEqual(batch.preview_summary["counts"]["conflict"], 0)

    def test_preview_batch_can_be_deleted_with_uploaded_file(self):
        batch = self.make_batch(LegacyImportBatch.ImportType.CHANNELS)
        build_import_preview(batch)
        stored_path = Path(batch.source_file.path)
        self.assertTrue(stored_path.exists())
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("legacy_import_delete", args=[batch.pk]))
        self.assertRedirects(response, reverse("legacy_import_list"))
        self.assertFalse(LegacyImportBatch.objects.filter(pk=batch.pk).exists())
        self.assertFalse(stored_path.exists())

    def test_completed_batch_cannot_be_deleted_but_can_be_archived_and_restored(self):
        batch = self.make_batch(LegacyImportBatch.ImportType.CHANNELS)
        build_import_preview(batch)
        confirm_import(batch, "tester")
        delete_response = self.client.post(reverse("legacy_import_delete", args=[batch.pk]))
        self.assertEqual(delete_response.status_code, 302)
        self.assertTrue(LegacyImportBatch.objects.filter(pk=batch.pk).exists())
        self.client.post(reverse("legacy_import_archive", args=[batch.pk]))
        batch.refresh_from_db()
        self.assertIsNotNone(batch.archived_at)
        self.client.post(reverse("legacy_import_restore", args=[batch.pk]))
        batch.refresh_from_db()
        self.assertIsNone(batch.archived_at)

    def test_excluded_sales_row_is_not_treated_as_previously_imported_next_time(self):
        first = self.make_batch(LegacyImportBatch.ImportType.OPERATIONS)
        build_import_preview(first)
        sales_row = first.rows.get(sheet_name="銷貨")
        apply_import_row_decision(
            sales_row,
            {},
            LegacyImportCorrection.Decision.EXCLUDE,
            "本次先不匯入銷貨",
            "tester",
        )
        confirm_import(first, "tester")
        second = self.make_batch(LegacyImportBatch.ImportType.OPERATIONS)
        build_import_preview(second)
        self.assertEqual(
            second.rows.get(sheet_name="銷貨").action,
            "create",
        )
