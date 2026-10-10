"""Excel 匯入、尚未完成的訂單尾款（方案 C）：總應付＝收款價＋強制險收入；車行收款打 V＝已收清。"""
from decimal import Decimal
from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from sales.models import LegacyImportBatch, PaymentRecord, SalesOrder, Store, payment_ledger_maintenance
from sales.services.imported_balance import imported_due
from sales.services.legacy_import import build_import_preview, confirm_import, file_sha256
from sales.services.payment_summary import payment_summary
from sales.tests.test_legacy_import import workbook_bytes


class ImportedBalanceTests(TestCase):
    def setUp(self):
        Store.objects.create(name="總店", code="MAIN")
        self.admin = get_user_model().objects.create_superuser("admin", password="Test-Only-123")
        tempdir = TemporaryDirectory()
        override = override_settings(MEDIA_ROOT=tempdir.name)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(tempdir.cleanup)

    def imported_order(self, *, plate=None, **raw):
        workbook = load_workbook(BytesIO(workbook_bytes()))
        workbook["銷貨"]["AS4"] = plate  # 沒有車牌＝待交車
        stream = BytesIO()
        workbook.save(stream)
        upload = SimpleUploadedFile("sales.xlsx", stream.getvalue())
        batch = LegacyImportBatch.objects.create(
            import_type="operations", source_file=upload, original_filename=upload.name,
            file_sha256=file_sha256(upload), file_size=len(stream.getvalue()), uploaded_by="tester",
        )
        build_import_preview(batch, sheets=["銷貨"])
        confirm_import(batch, "tester")
        order = SalesOrder.objects.get()
        snapshot = order.legacy_snapshot
        snapshot.raw_financials = {**snapshot.raw_financials, "強制險收入": 1500, **raw}
        snapshot.save(update_fields=["raw_financials"])
        return SalesOrder.objects.get(pk=order.pk)

    def receive(self, order, amount):
        with payment_ledger_maintenance():
            PaymentRecord.objects.create(
                order=order, item_name="尾款收款", received_amount=Decimal(amount), expected_amount=0,
                receipt_kind="customer", confirmed=True, payment_method="現金",
            )

    def test_unpaid_import_uses_excel_price_plus_insurance(self):
        order = self.imported_order()
        self.assertEqual(order.status, SalesOrder.Status.DELIVERY_PENDING)
        due = imported_due(order)
        self.assertEqual((due["price"], due["insurance"], due["total"]), (Decimal("70000"), Decimal("1500"), Decimal("71500")))
        self.assertFalse(due["paid_in_excel"])
        self.receive(order, 5000)
        summary = payment_summary(order)
        self.assertEqual(summary["customer_expected"], Decimal("71500"))
        self.assertEqual(summary["customer_due"], Decimal("66500"))
        self.assertEqual(summary["delivery_due"], Decimal("66500"))
        self.assertFalse(summary["customer_settled"])
        self.assertEqual(order.imported_balance["remaining"], Decimal("66500"))
        self.assertTrue(any("尾款尚未收清" in blocker for blocker in order.delivery_blockers()))
        self.receive(order, 66500)
        self.assertTrue(payment_summary(order)["customer_settled"])
        self.assertEqual(order.imported_balance["remaining"], Decimal("0"))

    def test_v_mark_means_already_paid(self):
        order = self.imported_order(**{"車行收款": "V"})
        balance = order.imported_balance
        self.assertTrue(balance["paid_in_excel"])
        self.assertEqual(balance["remaining"], Decimal("0"))
        self.assertEqual(balance["total"], Decimal("71500"))
        self.assertFalse(any("尾款尚未收清" in blocker for blocker in order.delivery_blockers()))
        self.assertFalse(
            PaymentRecord.objects.filter(order=order, confirmed=True).exclude(system_key__startswith="legacy_").exists(),
            "不補任何收款紀錄（只有匯入時的歷史收款列）",
        )

    def test_completed_import_is_untouched(self):
        order = self.imported_order(plate="ABC-1234")
        self.assertEqual(order.status, SalesOrder.Status.COMPLETED)
        self.assertIsNone(imported_due(order))
        self.assertIsNone(order.imported_balance)

    def test_installment_import_is_untouched(self):
        order = self.imported_order()
        SalesOrder.objects.filter(pk=order.pk).update(payment_type="installment")
        self.assertIsNone(imported_due(SalesOrder.objects.get(pk=order.pk)))

    def test_order_page_shows_remaining_balance(self):
        order = self.imported_order()
        self.receive(order, 5000)
        self.client.force_login(self.admin)
        from sales.tests.profit_helpers import unlock_profit
        unlock_profit(self, self.admin)
        response = self.client.get(reverse("order_detail", args=[order.pk]))
        self.assertContains(response, "尾款剩餘")
        self.assertContains(response, "$66500")
        self.assertContains(response, "Excel 收款價 $70000 ＋ 強制險 $1500")
