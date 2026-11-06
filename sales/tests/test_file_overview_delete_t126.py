"""「全部檔案」總覽也能直接刪除（使用者 2026-11-06 T-126）。

沿用各自原本的刪除路由（領牌、補助、下訂附件、單一檔案欄位）與權限；刪除前確認、原地更新；
已簽署文件不能刪並寫出原因；GET 不寫入；沒權限看不到刪除鈕、POST 被擋。
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.access.registry import SCREENS
from sales.models import LegacyImportBatch, OrderEvent, PaymentRecord, RegistrationDocument, SalesOrder, SubsidyDocument
from sales.tests import test_inplace_uploads as inplace
from sales.tests.test_inplace_uploads import png


class FileOverviewDeleteTests(inplace.InplaceUploadTests.__bases__[0]):
    setUpClass = inplace.InplaceUploadTests.setUpClass
    tearDownClass = inplace.InplaceUploadTests.tearDownClass
    setUp = inplace.InplaceUploadTests.setUp
    detail = inplace.InplaceUploadTests.detail

    def overview(self):
        html = self.detail()
        return html.split("各步驟已上傳的檔案", 1)[1]

    def make_files(self):
        registration = RegistrationDocument.objects.create(order=self.order, document_type="invoice", file=png("inv.png"))
        subsidy = SubsidyDocument.objects.create(order=self.order, document_type="other", name="切結書", file=png("s.png"))
        payment = PaymentRecord.objects.create(order=self.order, item_name="訂金", received_amount=1000, proof=png("p.png"))
        SalesOrder.objects.filter(pk=self.order.pk).update(id_front=png("idf.png").name)
        self.order.id_front = png("idf.png")
        self.order.signed_contract = png("contract.png")
        self.order.save(update_fields=["id_front", "signed_contract"])
        return registration, subsidy, payment

    def test_overview_offers_delete_for_every_file_and_reason_for_signed(self):
        registration, subsidy, payment = self.make_files()
        html = self.overview()
        for url in (reverse("registration_document_delete", args=[self.order.pk, registration.pk]),
                    reverse("subsidy_document_delete", args=[self.order.pk, subsidy.pk]),
                    reverse("order_item_file_delete", args=[self.order.pk, "payment_proof", payment.pk]),
                    reverse("order_file_delete", args=[self.order.pk, "id_front"])):
            self.assertIn(f'action="{url}" data-inplace-form data-confirm=', html)
        # 簽署檔也能刪（使用者 2026-11-06「全部都改成可以刪除修改」）。
        self.assertIn(f'action="{reverse("order_file_delete", args=[self.order.pk, "signed_contract"])}"', html)

    def test_payment_proof_and_id_photo_delete_with_event(self):
        _registration, _subsidy, payment = self.make_files()
        stored = payment.proof.name
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("order_item_file_delete", args=[self.order.pk, "payment_proof", payment.pk]))
            self.client.post(reverse("order_file_delete", args=[self.order.pk, "id_front"]))
        payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertFalse(payment.proof)
        self.assertFalse(self.order.id_front)
        self.assertFalse(payment.proof.storage.exists(stored))
        events = set(OrderEvent.objects.filter(order=self.order).values_list("event_type", flat=True))
        self.assertTrue({"payment_proof_deleted", "id_front_deleted"} <= events)

    def test_get_is_read_only(self):
        _registration, _subsidy, payment = self.make_files()
        self.client.get(reverse("order_item_file_delete", args=[self.order.pk, "payment_proof", payment.pk]))
        self.client.get(reverse("order_file_delete", args=[self.order.pk, "id_front"]))
        self.client.get(reverse("order_file_delete", args=[self.order.pk, "signed_contract"]))
        payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertTrue(payment.proof)
        self.assertTrue(self.order.id_front)
        self.assertTrue(self.order.signed_contract)

    def test_signed_contract_delete_resets_signing_state(self):
        from sales.services.document_signing import record_paper_upload
        self.make_files()
        record_paper_upload(self.order, "contract")
        self.order.save()
        self.assertTrue(self.order.has_signed_contract)
        self.assertTrue(self.order.signed_contract_fingerprint)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("order_file_delete", args=[self.order.pk, "signed_contract"]))
        self.order.refresh_from_db()
        self.assertFalse(self.order.has_signed_contract)
        self.assertEqual((self.order.signed_contract_method, self.order.signed_contract_fingerprint), ("", ""))
        self.assertIsNone(self.order.signed_contract_uploaded_at)
        event = OrderEvent.objects.get(order=self.order, event_type="signed_contract_deleted")
        self.assertIn("contract", event.description)
        # 刪除後可以重新上傳。
        self.assertIn(reverse("contract_upload", args=[self.order.pk]), self.detail())

    def test_without_permission_no_button_and_post_blocked(self):
        _registration, _subsidy, payment = self.make_files()
        viewer = get_user_model().objects.create_user("viewer3", password="test-pass-123")
        UserAccessState.objects.create(user=viewer, configured=True)
        ScreenAccessGrant.objects.bulk_create(
            ScreenAccessGrant(user=viewer, screen_key=screen.key, view=True, operate=screen.key != "work" and screen.operate)
            for screen in SCREENS)
        self.client.force_login(viewer)
        url = reverse("order_item_file_delete", args=[self.order.pk, "payment_proof", payment.pk])
        self.assertNotIn(url, self.detail())
        self.client.post(url)
        payment.refresh_from_db()
        self.assertTrue(payment.proof)


class ImportSourceDeleteTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", "", "test-pass-123")
        self.client.force_login(self.admin)

    def batch(self, status):
        return LegacyImportBatch.objects.create(
            import_type="operations", status=status, source_file=SimpleUploadedFile("src.xlsx", b"PK"),
            original_filename="113年銷貨.xlsx", file_sha256="0" * 64, file_size=2, uploaded_by="admin")

    def test_completed_batch_source_deletable_and_page_still_loads(self):
        batch = self.batch(LegacyImportBatch.Status.COMPLETED)
        stored = batch.source_file.name
        url = reverse("legacy_import_source_delete", args=[batch.pk])
        self.assertContains(self.client.get(reverse("legacy_import_detail", args=[batch.pk])), url)
        self.client.get(url)
        batch.refresh_from_db()
        self.assertTrue(batch.source_file)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url)
        batch.refresh_from_db()
        self.assertFalse(batch.source_file)
        self.assertFalse(batch.source_file.storage.exists(stored))
        record = batch.result_summary["source_file_deleted"]
        self.assertEqual((record["by"], record["filename"]), ("admin", "113年銷貨.xlsx"))
        page = self.client.get(reverse("legacy_import_detail", args=[batch.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "原始檔已由 admin 刪除")

    def test_preview_batch_keeps_source(self):
        batch = self.batch(LegacyImportBatch.Status.PREVIEW)
        self.client.post(reverse("legacy_import_source_delete", args=[batch.pk]))
        batch.refresh_from_db()
        self.assertTrue(batch.source_file)

    def test_completed_batch_source_replace_keeps_data_and_blocks_reprocess(self):
        from sales.services.legacy_import import build_import_preview
        batch = self.batch(LegacyImportBatch.Status.COMPLETED)
        rows_before = batch.rows.count()
        old_name = batch.source_file.name
        url = reverse("legacy_import_source_replace", args=[batch.pk])
        self.assertContains(self.client.get(reverse("legacy_import_detail", args=[batch.pk])), url)
        with mock.patch("sales.services.upload_validation.validate_excel_upload", side_effect=lambda upload: upload), \
                self.captureOnCommitCallbacks(execute=True):
            self.client.post(url, {"source_file": SimpleUploadedFile("114年銷貨.xlsx", b"PK-new")})
        batch.refresh_from_db()
        self.assertNotEqual(batch.source_file.name, old_name)
        self.assertEqual(batch.status, LegacyImportBatch.Status.COMPLETED)
        self.assertEqual(batch.rows.count(), rows_before)
        record = batch.result_summary["source_file_replacements"][-1]
        self.assertEqual((record["by"], record["old_filename"], record["new_filename"]), ("admin", "113年銷貨.xlsx", "114年銷貨.xlsx"))
        page = self.client.get(reverse("legacy_import_detail", args=[batch.pk]))
        self.assertContains(page, "舊檔：113年銷貨.xlsx")
        with self.assertRaises(ValueError):
            build_import_preview(batch)

    def test_preview_batch_cannot_replace(self):
        batch = self.batch(LegacyImportBatch.Status.PREVIEW)
        old_name = batch.source_file.name
        self.client.post(reverse("legacy_import_source_replace", args=[batch.pk]), {"source_file": SimpleUploadedFile("x.xlsx", b"PK")})
        batch.refresh_from_db()
        self.assertEqual(batch.source_file.name, old_name)


class InventoryHistoryPhotoDeleteTests(TestCase):
    def test_delete_snapshot_records_and_blocks_without_permission(self):
        from sales.models import Store, VehicleColor, VehicleInventory, VehicleInventoryHistory, VehicleModel
        admin = get_user_model().objects.create_superuser("admin", "", "test-pass-123")
        store = Store.objects.create(name="總店", code="HQ")
        model = VehicleModel.objects.create(brand="SUZUKI", name="SUI 125", energy_type=VehicleModel.EnergyType.GAS)
        color = VehicleColor.objects.create(vehicle_model=model, name="灰")
        vehicle = VehicleInventory.objects.create(vehicle_model=model, color=color, engine_number="ENG-H1",
                                                  ownership_store=store, location_store=store)
        history = VehicleInventoryHistory.objects.create(vehicle=vehicle, event_type=VehicleInventoryHistory.EventType.TRANSFERRED,
                                                         condition_photo_snapshot=png("snap.png"))
        url = reverse("inventory_history_photo_delete", args=[vehicle.pk, history.pk])
        viewer = get_user_model().objects.create_user("viewer4", password="test-pass-123")
        UserAccessState.objects.create(user=viewer, configured=True)
        ScreenAccessGrant.objects.bulk_create(
            ScreenAccessGrant(user=viewer, screen_key=screen.key, view=True, operate=screen.key != "inventory" and screen.operate)
            for screen in SCREENS)
        self.client.force_login(viewer)
        self.client.post(url)
        history.refresh_from_db()
        self.assertTrue(history.condition_photo_snapshot)
        self.client.force_login(admin)
        self.client.get(url)
        history.refresh_from_db()
        self.assertTrue(history.condition_photo_snapshot)
        stored = history.condition_photo_snapshot.name
        self.assertContains(self.client.get(reverse("inventory_edit", args=[vehicle.pk])), url)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url)
        history.refresh_from_db()
        self.assertFalse(history.condition_photo_snapshot)
        self.assertFalse(history.condition_photo_snapshot.storage.exists(stored))
        self.assertEqual(history.changes["photo_deleted"]["by"], "admin")
