"""匯入預覽與既有訂單比對：疑似重複、號碼已屬他人、匯入後 Excel 改動，以及用 Excel 更新既有訂單的保護。"""
from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from sales.models import LegacyImportBatch, LegacyImportRow, OrderChange, OrderEvent, SalesOrder, Store
from sales.services import import_order_review as review
from sales.services.legacy_import import build_import_preview, confirm_import, file_sha256
from sales.tests.test_legacy_import import workbook_bytes


class ImportOrderReviewTests(TestCase):
    def setUp(self):
        Store.objects.create(name="總店", code="MAIN")
        self.user = get_user_model().objects.create_superuser("admin", password="Test-Only-123")
        self.client.force_login(self.user)
        from sales.tests.profit_helpers import unlock_profit
        unlock_profit(self, self.user)
        self.tempdir = TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.tempdir.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.tempdir.cleanup)
        self.counter = 0

    def batch(self, **cells):
        """以預設銷貨列為底，套用指定儲存格後建立預覽（只匯銷貨）。"""
        workbook = load_workbook(BytesIO(workbook_bytes()))
        sales = workbook["銷貨"]
        for cell, value in cells.items():
            sales[cell] = value
        stream = BytesIO()
        workbook.save(stream)
        self.counter += 1
        upload = SimpleUploadedFile(f"sales-{self.counter}.xlsx", stream.getvalue())
        batch = LegacyImportBatch.objects.create(
            import_type="operations", source_file=upload, original_filename=upload.name,
            file_sha256=file_sha256(upload), file_size=len(stream.getvalue()), uploaded_by="tester",
        )
        build_import_preview(batch, sheets=["銷貨"])
        return batch

    def row(self, batch):
        return batch.rows.get(sheet_name="銷貨", source_row=4)

    def imported_order(self):
        first = self.batch()
        confirm_import(first, "tester")
        return SalesOrder.objects.get()

    def test_corrected_identifier_is_flagged_and_updates_existing_order(self):
        order = self.imported_order()
        second = self.batch(D4="XY-999")
        row = self.row(second)
        self.assertEqual(row.action, LegacyImportRow.Action.CONFLICT)
        self.assertIn(review.SAME_OWNER_MESSAGE, row.messages)
        [item] = review.row_reviews([row])
        self.assertEqual(item["kind"], review.SAME_OWNER)
        self.assertEqual(item["orders"][0]["order"], order)
        states = {field["key"]: field["state"] for field in item["orders"][0]["fields"]}
        self.assertEqual(states["identifier_raw"], "update")

        with self.assertRaises(ValueError):
            review.decide(row, decision="update", order_id=order.pk, fields=["identifier_raw"], reason="", actor_name="admin")
        review.decide(row, decision="update", order_id=order.pk, fields=["identifier_raw"],
                      reason="Excel 更正車架號碼", actor_name="admin")
        row.refresh_from_db()
        self.assertEqual(row.action, LegacyImportRow.Action.UPDATE)
        result = confirm_import(second, "tester")
        self.assertEqual(result["updated"], 1)
        self.assertEqual(SalesOrder.objects.count(), 1, "不會再建立重複訂單")
        order.legacy_snapshot.refresh_from_db()
        self.assertEqual(order.legacy_snapshot.vehicle_identifier, "XY-999")
        change = OrderChange.objects.get(order=order)
        self.assertIn("車輛識別（引擎／車身號碼）", change.changes)
        self.assertIn("Excel 更正車架號碼", change.reason)
        self.assertTrue(OrderEvent.objects.filter(order=order, event_type=review.EVENT).exists())

        third = self.batch(D4="XY-999")
        row = self.row(third)
        self.assertEqual(row.action, LegacyImportRow.Action.SKIP)
        self.assertFalse(review.REVIEW_MESSAGES.intersection(row.messages))

    def test_excel_change_after_import_can_update_only_untouched_fields(self):
        order = self.imported_order()
        second = self.batch(AS4="XYZ-9999", AY4="0911222333")
        row = self.row(second)
        self.assertEqual(row.action, LegacyImportRow.Action.SKIP)
        self.assertIn(review.CHANGED_MESSAGE, row.messages)

        # 匯入後在系統改過的電話不能被 Excel 覆蓋。
        SalesOrder.objects.filter(pk=order.pk).update(owner_phone="0900000000")
        [item] = review.row_reviews([row])
        states = {field["key"]: field["state"] for field in item["orders"][0]["fields"]}
        self.assertEqual(states["plate_number"], "update")
        self.assertEqual(states["owner_phone"], "system")
        with self.assertRaisesMessage(ValueError, "請勾選至少一個"):
            review.decide(row, decision="update", order_id=order.pk, fields=["owner_phone"], reason="測試", actor_name="admin")
        review.decide(row, decision="update", order_id=order.pk, fields=["plate_number", "owner_phone"],
                      reason="Excel 補車牌", actor_name="admin")
        row.refresh_from_db()
        self.assertEqual(row.mapped_data["_review"]["fields"], ["plate_number"])
        confirm_import(second, "tester")
        order.refresh_from_db()
        self.assertEqual(order.final_plate_number, "XYZ-9999")
        self.assertEqual(order.owner_phone, "0900000000")

    def test_changed_order_after_preview_fails_the_row_instead_of_overwriting(self):
        order = self.imported_order()
        second = self.batch(AS4="XYZ-9999")
        row = self.row(second)
        review.decide(row, decision="update", order_id=order.pk, fields=["plate_number"], reason="補車牌", actor_name="admin")
        SalesOrder.objects.filter(pk=order.pk).update(final_plate_number="MAN-0001")
        result = confirm_import(second, "tester")
        self.assertEqual(result["errors"], 1)
        order.refresh_from_db()
        self.assertEqual(order.final_plate_number, "MAN-0001")

    def test_blank_identifier_in_excel_can_be_cleared_when_chosen(self):
        """黃康洺情境：Excel 把號碼清空（號碼屬於另一位買家），可勾選清除既有訂單的號碼。"""
        order = self.imported_order()
        second = self.batch(D4=None)
        row = self.row(second)
        self.assertEqual(row.action, LegacyImportRow.Action.CONFLICT)
        [item] = review.row_reviews([row])
        states = {field["key"]: field["state"] for field in item["orders"][0]["fields"]}
        self.assertEqual(states["identifier_raw"], "clear")
        review.decide(row, decision="update", order_id=order.pk, fields=["identifier_raw"], reason="號碼屬於另一位買家", actor_name="admin")
        confirm_import(second, "tester")
        order.legacy_snapshot.refresh_from_db()
        self.assertEqual(order.legacy_snapshot.vehicle_identifier, "")
        self.assertEqual(SalesOrder.objects.count(), 1)

    def test_identifier_already_used_by_other_owner_needs_decision(self):
        self.imported_order()
        second = self.batch(AT4="另一位車主", E4="另一位車主", AW4="B223456789", B4="2026/09/01", CI4="2026/08/30")
        row = self.row(second)
        self.assertEqual(row.action, LegacyImportRow.Action.CONFLICT)
        self.assertIn(review.IDENTIFIER_TAKEN_MESSAGE, row.messages)
        order = SalesOrder.objects.get()
        with self.assertRaisesMessage(ValueError, "不能直接改成這位買家"):
            review.decide(row, decision="update", order_id=order.pk, fields=["owner_name"], reason="試圖改買家", actor_name="admin")
        [item] = review.row_reviews([row])
        self.assertFalse(item["can_update"])
        review.decide(row, decision="create", reason="確認是另一筆交易", actor_name="admin")
        row.refresh_from_db()
        self.assertEqual(row.action, LegacyImportRow.Action.CREATE)
        self.assertIn(review.IDENTIFIER_TAKEN_MESSAGE, row.messages, "仍新增時保留比對訊息")
        confirm_import(second, "tester")
        self.assertEqual(SalesOrder.objects.count(), 2)

    def test_manual_correction_clears_previous_decision(self):
        from sales.services.legacy_import import apply_import_row_decision
        order = self.imported_order()
        second = self.batch(D4="XY-999")
        row = self.row(second)
        review.decide(row, decision="update", order_id=order.pk, fields=["identifier_raw"], reason="更正號碼", actor_name="admin")
        row.refresh_from_db()
        apply_import_row_decision(row, {"identifier_raw": "XY-998"}, "correct", "再改一次", "admin")
        row.refresh_from_db()
        self.assertNotIn("_review", row.mapped_data)
        self.assertEqual(row.action, LegacyImportRow.Action.CONFLICT)

    def test_review_page_and_actions(self):
        self.imported_order()
        second = self.batch(D4="XY-999")
        row = self.row(second)
        detail = reverse("legacy_import_detail", args=[second.pk])
        page = self.client.get(detail)
        self.assertContains(page, "既有訂單比對")
        page = self.client.get(detail, {"review": "orders"})
        self.assertContains(page, f'id="review-row-{row.pk}"')
        self.assertContains(page, "用 Excel 更新這張訂單")
        self.assertContains(page, "確認是不同交易，仍新增")
        url = reverse("legacy_import_order_review", args=[second.pk, row.pk])
        response = self.client.post(url, {"decision": "exclude", "reason": "重複列"}, follow=True)
        self.assertContains(response, "已排除此列")
        row.refresh_from_db()
        self.assertEqual(row.action, LegacyImportRow.Action.EXCLUDE)
