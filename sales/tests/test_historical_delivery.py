"""歷史匯入單交車狀態（1.60.0）：Excel 有車牌＝已完成、沒有車牌＝待交車；補登車牌（手動或用 Excel 更新）即完成。"""
from datetime import date
from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import LegacyImportBatch, LegacyImportRow, OrderChange, OrderOperationsProfile, SalesOrder, Store
from sales.services import historical_delivery, import_order_review
from sales.services.legacy_import import build_import_preview, confirm_import, file_sha256
from sales.services.operations_sync import sync_order_operations
from sales.tests.test_legacy_import import workbook_bytes


class HistoricalDeliveryTests(TestCase):
    def setUp(self):
        Store.objects.create(name="總店", code="MAIN")
        self.admin = get_user_model().objects.create_superuser("admin", password="Test-Only-123")
        tempdir = TemporaryDirectory()
        override = override_settings(MEDIA_ROOT=tempdir.name)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(tempdir.cleanup)
        self.counter = 0

    def run_import(self, **cells):
        workbook = load_workbook(BytesIO(workbook_bytes()))
        for cell, value in cells.items():
            workbook["銷貨"][cell] = value
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

    def test_rows_without_plate_import_as_delivery_pending(self):
        confirm_import(self.run_import(AS4=None), "tester")
        order = SalesOrder.objects.get()
        self.assertEqual(order.status, SalesOrder.Status.DELIVERY_PENDING)
        self.assertIsNone(order.delivered_at)
        self.assertIsNone(order.registration_completed_at)
        self.assertIsNotNone(order.registration_date, "保留預計領牌日期")

    def test_rows_with_plate_import_as_completed(self):
        confirm_import(self.run_import(), "tester")
        order = SalesOrder.objects.get()
        self.assertEqual(order.status, SalesOrder.Status.COMPLETED)
        self.assertEqual(order.delivered_by, "歷史資料匯入")

    def test_admin_completes_with_plate_and_date(self):
        confirm_import(self.run_import(AS4=None), "tester")
        order = SalesOrder.objects.get()
        self.client.force_login(self.admin)
        from sales.tests.profit_helpers import unlock_profit
        unlock_profit(self, self.admin)
        page = self.client.get(reverse("order_detail", args=[order.pk]))
        self.assertContains(page, "補登車牌並完成交車")
        response = self.client.post(reverse("historical_delivery_complete", args=[order.pk]),
                                    {"plate": "new-0001", "delivered_on": "2026-10-12", "reason": "已領牌交車"}, follow=True)
        self.assertContains(response, "已補登車牌 NEW-0001")
        order.refresh_from_db()
        self.assertEqual(order.status, SalesOrder.Status.COMPLETED)
        self.assertEqual(order.final_plate_number, "NEW-0001")
        self.assertEqual(order.delivered_at.date(), date(2026, 10, 12))
        self.assertTrue(OrderChange.objects.filter(order=order, reason__contains="補登車牌").exists())
        self.assertNotContains(self.client.get(reverse("order_detail", args=[order.pk])),
                               reverse("historical_delivery_complete", args=[order.pk]), msg_prefix="完成後不再顯示補登表單")

    def test_completion_validates_and_staff_cannot_use_it(self):
        confirm_import(self.run_import(AS4=None), "tester")
        order = SalesOrder.objects.get()
        with self.assertRaisesMessage(ValueError, "請填寫車牌號碼"):
            historical_delivery.complete_imported_order(order.pk, plate="", delivered_on=date(2026, 10, 1), actor="a", reason="原因")
        with self.assertRaisesMessage(ValueError, "請填寫原因"):
            historical_delivery.complete_imported_order(order.pk, plate="X-1", delivered_on=date(2026, 10, 1), actor="a", reason="")
        staff = get_user_model().objects.create_user("staff", password="Test-Only-123")
        UserAccessState.objects.create(user=staff, configured=True)
        ScreenAccessGrant.objects.create(user=staff, screen_key="orders", view=True, operate=True)
        self.client.force_login(staff)
        response = self.client.post(reverse("historical_delivery_complete", args=[order.pk]),
                                    {"plate": "X-1", "delivered_on": "2026-10-01", "reason": "試圖"})
        self.assertEqual(response.status_code, 403)
        order.refresh_from_db()
        self.assertEqual(order.status, SalesOrder.Status.DELIVERY_PENDING)

    def test_reopen_completed_order_without_plate(self):
        confirm_import(self.run_import(), "tester")
        order = SalesOrder.objects.get()
        with self.assertRaisesMessage(ValueError, "已有車牌"):
            historical_delivery.reopen_imported_order(order.pk, actor="a", reason="測試")
        SalesOrder.objects.filter(pk=order.pk).update(final_plate_number="")
        historical_delivery.reopen_imported_order(order.pk, actor="a", reason="沒有車牌")
        order.refresh_from_db()
        self.assertEqual((order.status, order.delivered_by, order.delivered_at), (SalesOrder.Status.DELIVERY_PENDING, "", None))

    def test_excel_update_with_plate_completes_order(self):
        confirm_import(self.run_import(AS4=None), "tester")
        order = SalesOrder.objects.get()
        second = self.run_import()
        row = second.rows.get(sheet_name="銷貨", source_row=4)
        self.assertEqual(row.action, LegacyImportRow.Action.SKIP)
        self.assertIn(import_order_review.CHANGED_MESSAGE, row.messages)
        import_order_review.decide(row, decision="update", order_id=order.pk, fields=["plate_number"],
                                   reason="Excel 補車牌", actor_name="admin")
        confirm_import(second, "tester")
        order.refresh_from_db()
        self.assertEqual(order.status, SalesOrder.Status.COMPLETED)
        self.assertEqual(order.final_plate_number, "ABC-1234")
        self.assertEqual(order.delivered_at.date(), order.registration_date)

    def test_pending_historical_order_keeps_imported_financials(self):
        confirm_import(self.run_import(AS4=None), "tester")
        order = SalesOrder.objects.get()
        profile = OrderOperationsProfile.objects.get(order=order)
        self.assertTrue(profile.legacy_finance_reconciliation)
        OrderOperationsProfile.objects.filter(pk=profile.pk).update(vehicle_cost=54321)
        sync_order_operations(order.pk)
        profile.refresh_from_db()
        self.assertEqual(profile.vehicle_cost, 54321, "待交車的歷史匯入單也不被一般同步覆寫財務")
