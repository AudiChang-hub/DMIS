from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from io import BytesIO
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from sales.models import LegacyImportBatch, LegacyImportRow, SalesOrder, Store, PaymentRecord, OrderOperationsProfile, OrderChange, VehicleInventory, LegacyImportCorrection
from sales.services.legacy_import import build_import_preview, confirm_import, file_sha256
from sales.services.historical_replacement import preview_token, replacement_preview, replace_historical_buyer
from sales.tests.test_legacy_import import workbook_bytes


class ReplacementFixture:
    def setUp(self):
        super().setUp()
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        override = override_settings(MEDIA_ROOT=self.temp.name)
        override.enable()
        self.addCleanup(override.disable)
        Store.objects.create(name="總店", code="MAIN")
        self.admin = get_user_model().objects.create_superuser("admin", password="test-only")
        workbook = load_workbook(BytesIO(workbook_bytes()))
        workbook["銷貨"]["AS4"] = ""
        workbook["銷貨"]["J4"] = 0
        workbook["銷貨"]["AT4"] = "驗收原買家"
        stream = BytesIO()
        workbook.save(stream)
        upload = SimpleUploadedFile("replacement.xlsx", stream.getvalue())
        self.batch = LegacyImportBatch.objects.create(import_type="operations", source_file=upload,
            original_filename="replacement.xlsx", file_sha256=file_sha256(upload), file_size=stream.tell())
        build_import_preview(self.batch)
        confirm_import(self.batch, "tester")
        original = self.batch.rows.get(sheet_name="銷貨")
        self.order = SalesOrder.objects.get(pk=original.committed_pk)
        self.vehicle_id = self.order.allocated_vehicle_id
        self.row = LegacyImportRow.objects.create(batch=self.batch, sheet_name="銷貨", source_row=1752,
            fingerprint="replacement", natural_key="replacement", action="error", raw_data={},
            mapped_data={**original.mapped_data, "owner_name": "驗收新買家", "owner_id_number": "B223456789"})
        self.url = reverse("historical_buyer_replacement", args=[self.batch.pk, self.row.pk, self.order.pk])
        self.client.force_login(self.admin)

    def data(self):
        self.row.refresh_from_db()
        self.order.refresh_from_db()
        preview = replacement_preview(self.row, self.order)
        return dict(preview_token=preview_token(preview, self.admin), confirm_number=self.order.number,
            original_unregistered=True, original_undelivered=True, finances_checked=True, incoming_status="completed",
            collection_status="none", actual_received="0", reason="驗收：原買家退訂，未實際領牌交車")

    def execute(self, data=None, user=None):
        return replace_historical_buyer(row_id=self.row.pk, order_id=self.order.pk, user=user or self.admin,
                                       data=data if data is not None else self.data())


class HistoricalReplacementTests(ReplacementFixture, TestCase):
    def test_preview_readonly_and_no_prechecked_facts(self):
        before = list(SalesOrder.objects.values())
        response = self.client.get(self.url)
        self.assertContains(response, "驗收原買家 → 驗收新買家")
        for name in ("original_unregistered", "original_undelivered", "finances_checked"):
            self.assertFalse(response.context["form"][name].value())
        self.assertEqual(before, list(SalesOrder.objects.values()))
        self.assertIn("no-store", response["Cache-Control"])

    def test_success_preserves_original_finances_and_snapshot(self):
        old_profile = list(OrderOperationsProfile.objects.filter(order=self.order).values())
        old_payments = list(self.order.payment_records.values())
        snapshot_id = self.order.legacy_snapshot.pk
        new = self.execute()
        self.order.refresh_from_db()
        self.row.refresh_from_db()
        self.assertEqual(self.order.status, SalesOrder.Status.CANCELLED)
        self.assertIsNone(self.order.allocated_vehicle_id)
        self.assertIsNone(self.order.registration_date)
        self.assertIsNone(self.order.delivered_at)
        self.assertEqual(self.order.legacy_snapshot.pk, snapshot_id)
        self.assertEqual(old_profile, list(OrderOperationsProfile.objects.filter(order=self.order).values()))
        self.assertEqual(old_payments, list(self.order.payment_records.values()))
        self.assertEqual(new.allocated_vehicle_id, self.vehicle_id)
        self.assertEqual(new.owner_name, "驗收新買家")
        self.assertEqual(new.status, SalesOrder.Status.COMPLETED)
        self.assertEqual(self.row.action, "create")
        self.assertEqual(str(new.pk), self.row.committed_pk)
        self.assertTrue(OrderChange.objects.filter(order=self.order, changes__status__after="cancelled").exists())
        with self.assertRaises(ValidationError):
            self.execute()
        self.assertEqual(SalesOrder.objects.count(), 2)

    def test_atomic_failure_restores_everything(self):
        data = self.data()
        before = list(SalesOrder.objects.values())
        before_vehicles = list(VehicleInventory.objects.values())
        before_rows = list(LegacyImportRow.objects.values())
        before_corrections = LegacyImportCorrection.objects.count()
        with patch("sales.services.historical_replacement.retry_completed_import_row", return_value={"ok": False, "error": "模擬失敗"}):
            with self.assertRaisesMessage(ValidationError, "均已回復"):
                self.execute(data)
        self.assertEqual(before, list(SalesOrder.objects.values()))
        self.assertEqual(before_vehicles, list(VehicleInventory.objects.values()))
        self.assertEqual(before_rows, list(LegacyImportRow.objects.values()))
        self.assertEqual(before_corrections, LegacyImportCorrection.objects.count())

    def test_real_import_failure_rolls_back_cancellation(self):
        self.row.mapped_data["owner_email"] = "not-an-email"
        self.row.save()
        with self.assertRaises(ValidationError):
            self.execute()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, SalesOrder.Status.COMPLETED)
        self.assertEqual(self.order.allocated_vehicle_id, self.vehicle_id)
        self.assertEqual(SalesOrder.objects.count(), 1)

    def test_permissions_and_csrf(self):
        for username, superuser in (("staff", False), ("other-admin", True)):
            user = get_user_model().objects.create_user(username, is_staff=True, is_superuser=superuser)
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertEqual(self.client.post(self.url, self.data()).status_code, 403)
            with self.assertRaises(PermissionDenied):
                self.execute(user=user)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        self.assertEqual(csrf_client.post(self.url, self.data()).status_code, 403)

    def test_required_facts_and_number(self):
        for field in ("original_unregistered", "original_undelivered", "finances_checked", "incoming_status", "reason", "confirm_number"):
            data = self.data()
            data.pop(field)
            self.assertEqual(self.client.post(self.url, data).status_code, 400)
        self.assertEqual(SalesOrder.objects.count(), 1)

    def test_pending_order_preserves_schedule_and_requires_real_completion(self):
        self.row.mapped_data.update(registration_date="2026-09-11", cash_received="3000", card_received="2000", payment_confirmed=True)
        self.row.save()
        data = self.data()
        data.update(incoming_status="pending", pending_vehicle_price="70000", pending_balance="71000")
        old_payments = list(self.order.payment_records.values())
        new = self.execute(data)
        self.assertEqual(new.status, SalesOrder.Status.ALLOCATED)
        self.assertIsNone(new.registration_completed_at)
        self.assertIsNone(new.delivered_at)
        self.assertEqual(str(new.registration_date), "2026-09-11")
        self.assertEqual(new.allocated_vehicle.status, VehicleInventory.Status.RESERVED)
        self.assertEqual(new.vehicle_price, 70000)
        self.assertEqual(new.actual_balance, 71000)
        balance = new.payment_records.get(system_key="balance")
        self.assertEqual(balance.expected_amount, 71000)
        self.assertEqual(balance.received_amount, 5000)
        self.assertEqual(new.actual_balance - balance.received_amount, 66000)
        self.assertFalse(new.payment_records.filter(system_key__startswith="legacy_").exists())
        self.assertEqual(old_payments, list(self.order.payment_records.values()))
        with self.assertRaises(ValidationError):
            new.complete_registration("admin")
        from django.utils import timezone
        with self.assertRaises(ValidationError):
            new.complete_delivery(timezone.now(), "admin")

    def test_pending_order_never_assumes_zero_price_or_receivable(self):
        data = self.data()
        data["incoming_status"] = "pending"
        with self.assertRaisesMessage(ValidationError, "必須核對新訂單金額"):
            self.execute(data)
        self.assertEqual(SalesOrder.objects.count(), 1)

    def test_future_registration_cannot_be_declared_completed(self):
        from datetime import timedelta
        from django.utils import timezone
        self.row.mapped_data["registration_date"] = str(timezone.localdate() + timedelta(days=1))
        self.row.save()
        with self.assertRaisesMessage(ValidationError, "未來日期"):
            self.execute()

    def test_pending_receivable_cannot_be_less_than_incoming_receipts(self):
        self.row.mapped_data["cash_received"] = "3000"
        self.row.save()
        data = self.data()
        data.update(incoming_status="pending", pending_vehicle_price="70000", pending_balance="1000")
        with self.assertRaisesMessage(ValidationError, "低於本次 Excel 實收"):
            self.execute(data)

    def test_pending_invalid_receipts_cannot_release_original_vehicle(self):
        for amount in ("-100", "NaN", "Infinity"):
            self.row.mapped_data["cash_received"] = amount
            self.row.save()
            data = self.data()
            data.update(incoming_status="pending", pending_vehicle_price="70000", pending_balance="70000")
            with self.assertRaises(ValidationError):
                self.execute(data)
            self.order.refresh_from_db()
            self.assertEqual(self.order.allocated_vehicle_id, self.vehicle_id)

    def test_successful_post_redirects_to_new_order(self):
        response = self.client.post(self.url, self.data())
        self.row.refresh_from_db()
        self.assertRedirects(response, reverse("order_detail", args=[self.row.committed_pk]), fetch_redirect_response=False)

    def test_foreign_vehicle_and_expired_preview(self):
        data = self.data()
        with patch("django.core.signing.time.time", return_value=99999999999):
            with self.assertRaises(ValidationError):
                self.execute(data)
        self.row.mapped_data["identifier"] = "SOMEOTHERBIKE"
        self.row.mapped_data["identifier_raw"] = "SOMEOTHERBIKE"
        self.row.save()
        with self.assertRaisesMessage(ValidationError, "不相符"):
            self.execute()

    def test_formal_documents_block_replacement(self):
        from sales.models import RegistrationDocument
        RegistrationDocument.objects.create(order=self.order, document_type="new_license", file="test-license.jpg")
        with self.assertRaisesMessage(ValidationError, "領牌文件"):
            self.execute()

    def test_settled_bonus_cannot_be_rewritten(self):
        from datetime import date
        from sales.models import SalesSource, DealerVolumeBonusRule, DealerVolumeBonusSettlement, DealerVolumeBonusAllocation
        dealer = SalesSource.objects.create(name="驗收車行", source_type="dealer")
        rule = DealerVolumeBonusRule.objects.create(dealer=dealer, starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 31))
        settlement = DealerVolumeBonusSettlement.objects.create(rule=rule, dealer=dealer)
        allocation = DealerVolumeBonusAllocation.objects.create(settlement=settlement, order=self.order, amount=500)
        with self.assertRaisesMessage(ValidationError, "已結算"):
            self.execute()
        allocation.refresh_from_db()
        self.assertEqual(allocation.amount, 500)

    def test_signed_preview_and_stale_data(self):
        data = self.data()
        OrderOperationsProfile.objects.filter(order=self.order).update(vehicle_cost=123)
        with self.assertRaisesMessage(ValidationError, "資料已變更"):
            self.execute(data)
        for token in ("", "bad-token"):
            data = self.data()
            data["preview_token"] = token
            with self.assertRaises(ValidationError):
                self.execute(data)

    def test_evidence_manual_completion_and_same_buyer_blocked(self):
        for updates in ({"final_plate_number": "ABC-1234"}, {"delivered_by": "正式交付"}, {"owner_name": "驗收新買家"}):
            before = {key: getattr(self.order, key) for key in updates}
            SalesOrder.objects.filter(pk=self.order.pk).update(**updates)
            with self.assertRaises(ValidationError):
                self.execute()
            SalesOrder.objects.filter(pk=self.order.pk).update(**before)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, SalesOrder.Status.COMPLETED)

    def test_recorded_receipts_require_full_refund_and_preserve_payment(self):
        PaymentRecord.objects.create(order=self.order, item_name="原買家訂金", received_amount=5000, expected_amount=5000, confirmed=True)
        with self.assertRaises(ValidationError):
            self.execute()
        data = self.data()
        data.update(collection_status="refunded", actual_received="5000", refund_on="2026-01-01", refund_method="transfer", refund_reference="驗收退款憑據")
        for missing in ("refund_on", "refund_method", "refund_reference"):
            invalid = deepcopy(data)
            invalid.pop(missing)
            with self.assertRaises(ValidationError):
                self.execute(invalid)
        before = list(self.order.payment_records.values())
        new = self.execute(data)
        self.order.refresh_from_db()
        self.assertEqual(self.order.refund_amount, 5000)
        self.assertEqual(before, list(self.order.payment_records.values()))
        self.assertFalse(new.payment_records.filter(received_amount__gt=0).exists())


@skipUnless(connection.vendor == "postgresql", "PostgreSQL 列鎖驗證")
class HistoricalReplacementConcurrencyTests(ReplacementFixture, TransactionTestCase):
    def test_double_submit_creates_only_one_replacement(self):
        self.assert_single_replacement(self.data())

    def test_double_submit_pending_order_creates_only_one_replacement(self):
        data = self.data()
        data.update(incoming_status="pending", pending_vehicle_price="70000", pending_balance="70000")
        self.assert_single_replacement(data)

    def assert_single_replacement(self, data):
        barrier = Barrier(2)
        def submit():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    self.execute(data)
                    return "created"
                except ValidationError:
                    return "blocked"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: submit(), range(2)))
        self.assertCountEqual(results, ["created", "blocked"])
        self.assertEqual(SalesOrder.objects.count(), 2)
