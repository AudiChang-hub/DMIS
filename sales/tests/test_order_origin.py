"""訂單來源標記（1.86.23）：手動開單／Excel 匯入／Excel 匯入已修改，顯示在訂單編號下方。"""
from datetime import date
from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from openpyxl import load_workbook

from sales.models import (
    LegacyImportBatch, LegacyImportRow, LegacySalesSnapshot, OrderEvent, SalesOrder, Store, VehicleColor, VehicleModel,
)
from sales.services import historical_delivery, import_order_review
from sales.services.legacy_import import build_import_preview, confirm_import, file_sha256
from sales.services.order_origin import (
    IMPORTED, IMPORTED_EDITED, MANUAL, attach_order_origin, current_order_origin, order_origin, with_order_origin,
)
from sales.tests.test_legacy_import import workbook_bytes


class OrderOriginRuleTests(TestCase):
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
        upload = SimpleUploadedFile(f"origin-{self.counter}.xlsx", stream.getvalue())
        batch = LegacyImportBatch.objects.create(
            import_type="operations", source_file=upload, original_filename=upload.name,
            file_sha256=file_sha256(upload), file_size=len(stream.getvalue()), uploaded_by="tester",
        )
        build_import_preview(batch, sheets=["銷貨"])
        return batch

    def imported_order(self, **cells):
        confirm_import(self.run_import(**cells), "tester")
        return SalesOrder.objects.filter(legacy_snapshot__isnull=False).get()

    def origin(self, order):
        return order_origin(SalesOrder.objects.get(pk=order.pk))

    def test_system_order_is_manual_and_import_is_imported(self):
        model = VehicleModel.objects.create(brand="測試", name="來源機種", energy_type="gas")
        manual = SalesOrder.objects.create(owner_name="手動客", owner_phone="0912345678", owner_address="合成地址",
                                           owner_id_number="A123456789", vehicle_model=model,
                                           color=VehicleColor.objects.create(vehicle_model=model, name="白"))
        self.assertEqual(self.origin(manual).key, MANUAL)
        self.assertEqual(self.origin(manual).label, "手動開單")
        imported = self.imported_order()
        self.assertEqual(self.origin(imported).key, IMPORTED)
        self.assertEqual(self.origin(imported).label, "Excel 匯入")

    def test_reimport_update_and_excel_plate_completion_are_not_user_edits(self):
        order = self.imported_order(AS4=None)
        second = self.run_import()
        row = second.rows.get(sheet_name="銷貨", source_row=4)
        import_order_review.decide(row, decision="update", order_id=order.pk, fields=["plate_number"],
                                   reason="Excel 補車牌", actor_name="admin")
        confirm_import(second, "tester")
        order.refresh_from_db()
        self.assertEqual(order.status, SalesOrder.Status.COMPLETED, "前提：重新匯入補上車牌並完成交車")
        self.assertEqual(set(order.events.values_list("event_type", flat=True)),
                         {"legacy_import_update", historical_delivery.EVENT_IMPORT_COMPLETED})
        self.assertEqual(self.origin(order).key, IMPORTED)

    def test_views_classification_scripts_and_no_change_saves_are_not_user_edits(self):
        order = self.imported_order()
        for event_type, actor, description in [
            ("secret_viewed", "admin", "查看車控密碼"),
            ("identity_document_printed", "admin", "列印證件"),
            ("order_closed", "admin", "確認結案"),
            ("deletion_request", "admin", "申請刪除"),
            ("legacy_finance_repaired", "歷史財務核對修復", "核對"),
            ("updated", "系統（1.63.0 選號費搬移）", "改記為選號費"),
            ("order_updated", "admin（依使用者指示）", "依 Excel 第 4 列補登"),
            ("updated", "Sylvia", "修改訂單（0 個項目）"),
            ("operations_updated", "Sylvia", "更新營運與對帳資料（0 個欄位）"),
            ("historical_delivery_reopened", "admin", "沒有車牌，改回待交車"),
            ("allocated", "", "沒有操作人"),
        ]:
            OrderEvent.objects.create(order=order, event_type=event_type, actor_name=actor, description=description)
        self.assertEqual(self.origin(order).key, IMPORTED)

    def test_user_edit_marks_imported_order_as_edited(self):
        order = self.imported_order(AS4=None)
        self.client.force_login(self.admin)
        response = self.client.post(reverse("historical_delivery_complete", args=[order.pk]),
                                    {"plate": "new-0001", "delivered_on": "2026-10-12", "reason": "已領牌交車"})
        self.assertEqual(response.status_code, 302)
        origin = self.origin(order)
        self.assertEqual((origin.key, origin.label, origin.edited_by), (IMPORTED_EDITED, "Excel 匯入已修改", "admin"))
        OrderEvent.objects.create(order=order, event_type="operations_updated", actor_name="Sylvia",
                                  description="更新營運與對帳資料（2 個欄位）")
        self.assertEqual(self.origin(order).edited_by, "Sylvia", "顯示最後一次修改的人")
        page = self.client.get(reverse("order_detail", args=[order.pk]))
        self.assertContains(page, 'data-order-origin="imported_edited"')
        self.assertContains(page, "最後修改 Sylvia")
        overview = self.client.get(reverse("order_overview", args=[order.pk]))
        self.assertContains(overview, "Excel 匯入已修改")

    def test_annotation_matches_single_order_rule(self):
        order = self.imported_order()
        OrderEvent.objects.create(order=order, event_type="updated", actor_name="Sylvia", description="修改訂單（3 個項目）")
        annotated = with_order_origin(SalesOrder.objects.filter(pk=order.pk)).get()
        self.assertTrue(annotated.origin_imported)
        self.assertEqual(annotated.origin_edited_by, "Sylvia")
        self.assertEqual(order_origin(annotated).key, IMPORTED_EDITED)


class OrderOriginListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", password="Test-Only-123")
        cls.model = VehicleModel.objects.create(brand="測試", name="列表機種", energy_type="gas")
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="白")
        cls.batch = LegacyImportBatch.objects.create(
            import_type="operations", source_file=SimpleUploadedFile("list.xlsx", b"x"), original_filename="list.xlsx",
            file_sha256="0" * 64, file_size=1, uploaded_by="tester",
        )
        cls.rows = 0

    def make_orders(self, count):
        """每輪三種各一張：手動、匯入、匯入後有人修改。"""
        for index in range(count):
            for kind in (MANUAL, IMPORTED, IMPORTED_EDITED):
                order = SalesOrder.objects.create(
                    owner_name=f"列表{kind}{index}", owner_phone="0912345678", owner_address="合成地址",
                    owner_id_number="A123456789", vehicle_model=self.model, color=self.color, order_date=date(2026, 10, 1),
                )
                if kind == MANUAL:
                    continue
                type(self).rows += 1
                row = LegacyImportRow.objects.create(batch=self.batch, sheet_name="銷貨", source_row=self.rows,
                                                     fingerprint=f"{self.rows:064d}", action=LegacyImportRow.Action.CREATE)
                LegacySalesSnapshot.objects.create(order=order, import_row=row)
                if kind == IMPORTED_EDITED:
                    OrderEvent.objects.create(order=order, event_type="updated", actor_name="Sylvia",
                                              description="修改訂單（1 個項目）")

    def list_queries(self):
        self.client.force_login(self.admin)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("order_list"), {"tab": "open", "per_page": 50})
        self.assertEqual(response.status_code, 200)
        return response, len(queries)

    def test_order_list_shows_three_marks_without_per_order_queries(self):
        self.make_orders(1)
        response, few = self.list_queries()
        for label in ("手動開單", "Excel 匯入", "Excel 匯入已修改"):
            self.assertContains(response, f'<b class="order-origin__label">{label}</b>')
        self.make_orders(4)
        _response, many = self.list_queries()
        self.assertEqual(few, many, "多 12 張訂單不能多查詢（來源標記與匯入判斷用子查詢）")

    def test_related_lists_attach_marks_in_one_query(self):
        self.make_orders(3)
        orders = list(SalesOrder.objects.order_by("pk"))
        with self.assertNumQueries(1):
            attach_order_origin(orders)
            keys = [order_origin(order).key for order in orders]
        self.assertEqual(keys, [MANUAL, IMPORTED, IMPORTED_EDITED] * 3)
        edited = orders[2]
        OrderEvent.objects.create(order=orders[1], event_type="updated", actor_name="Nina", description="修改訂單（2 個項目）")
        self.assertEqual(current_order_origin(orders[1]).key, IMPORTED_EDITED, "存檔後重新判斷，不沿用舊標記")
        self.assertEqual(order_origin(edited).edited_by, "Sylvia")

    def test_recycle_bin_renders_marks(self):
        self.make_orders(2)
        self.client.force_login(self.admin)
        SalesOrder.objects.filter(owner_name__startswith="列表imported_edited").update(deleted_at=date(2026, 10, 18))
        response = self.client.get(reverse("order_recycle_bin"))
        self.assertContains(response, "Excel 匯入已修改", count=2)

    def test_returned_after_delivery_orders_keep_origin_with_returned_status(self):
        """交車後退車（1.86.22，例外結案＋有交車紀錄）：退車是人員操作，匯入單算已修改，手動單仍是手動開單。"""
        from django.utils import timezone
        from sales.services.order_return import EVENT_TYPE
        self.make_orders(1)
        manual, imported, _edited = SalesOrder.objects.order_by("pk")
        for order in (manual, imported):
            SalesOrder.objects.filter(pk=order.pk).update(
                status=SalesOrder.Status.EXCEPTION_CLOSED, delivered_at=timezone.now(), delivered_by="admin")
            OrderEvent.objects.create(order=order, event_type=EVENT_TYPE, actor_name="admin", description="交車後退車")
        self.assertEqual(order_origin(SalesOrder.objects.get(pk=manual.pk)).key, MANUAL)
        self.assertEqual(order_origin(SalesOrder.objects.get(pk=imported.pk)).key, IMPORTED_EDITED)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("order_list"), {"tab": "cancelled"})
        self.assertContains(response, "已退車")
        self.assertContains(response, 'data-order-origin="manual"')
        self.assertContains(response, 'data-order-origin="imported_edited"')
        page = self.client.get(reverse("order_detail", args=[imported.pk]))
        self.assertContains(page, "已退車")
        self.assertContains(page, "最後修改 admin")
