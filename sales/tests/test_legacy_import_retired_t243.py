"""T-243：舊 Excel 匯入（銷貨、進貨、車行名冊三種）停用，只拿掉入口；已匯入的資料與相關功能照常。"""
from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from sales.legacy_import_retired import RETIRED_MESSAGE
from sales.models import LegacyImportBatch, LegacyImportRow, LegacySalesSnapshot, SalesOrder, SalesSource, Store
from sales.services.home_favorites import LINKS
from sales.services.legacy_import import build_import_preview, confirm_import, file_sha256
from sales.services.order_search import rebuild_order_search_index
from sales.tests.test_legacy_import import workbook_bytes


class LegacyImportRetiredTests(TestCase):
    def setUp(self):
        Store.objects.create(name="總店", code="MAIN")
        self.admin = get_user_model().objects.create_superuser("admin", password="Test-Only-123")
        self.client.force_login(self.admin)
        tempdir = TemporaryDirectory()
        override = override_settings(MEDIA_ROOT=tempdir.name)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(tempdir.cleanup)
        self.counter = 0

    def preview_batch(self):
        self.counter += 1
        data = workbook_bytes()
        upload = SimpleUploadedFile(f"retired-{self.counter}.xlsx", data)
        batch = LegacyImportBatch.objects.create(
            import_type="operations", source_file=upload, original_filename=upload.name,
            file_sha256=file_sha256(upload), file_size=len(data), uploaded_by="tester",
        )
        build_import_preview(batch, sheets=["銷貨"])
        return batch

    def imported_order(self):
        batch = self.preview_batch()
        confirm_import(batch, "tester")
        return batch, SalesOrder.objects.get(legacy_snapshot__isnull=False)

    def assert_retired(self, response):
        self.assertRedirects(response, reverse("order_list"), fetch_redirect_response=False)
        self.assertIn(RETIRED_MESSAGE, [str(message) for message in get_messages(response.wsgi_request)])

    def test_old_urls_redirect_to_the_order_list_and_never_import(self):
        batch = self.preview_batch()
        row = batch.rows.filter(sheet_name="銷貨").first()
        rows_before = LegacyImportRow.objects.count()
        pk = {"pk": batch.pk}
        row_kwargs = {**pk, "row_pk": row.pk}
        gets = [
            reverse("legacy_import_list"),
            reverse("legacy_import_detail", kwargs=pk),
            reverse("legacy_import_status", kwargs=pk),
        ]
        posts = [
            reverse("legacy_import_confirm", kwargs=pk),
            reverse("legacy_import_delete", kwargs=pk),
            reverse("legacy_import_archive", kwargs=pk),
            reverse("legacy_import_restore", kwargs=pk),
            reverse("legacy_import_source_delete", kwargs=pk),
            reverse("legacy_import_source_replace", kwargs=pk),
            reverse("legacy_import_row_decide", kwargs=row_kwargs),
            reverse("legacy_import_order_review", kwargs=row_kwargs),
            reverse("legacy_import_master_resolve", kwargs={**pk, "mapping_type": "vehicle_model"}),
            reverse("legacy_import_master_restore", kwargs={**pk, "mapping_type": "vehicle_model"}),
            reverse("historical_buyer_replacement", kwargs={**row_kwargs, "order_pk": 1}),
            reverse("historical_date_change", kwargs={**row_kwargs, "order_pk": 1}),
        ]
        for url in gets:
            with self.subTest(url=url):
                self.assert_retired(self.client.get(url))
        for url in posts:
            with self.subTest(url=url):
                self.assert_retired(self.client.post(url, {"confirm": "1", "decision": "include"}))
        # 上傳也只導回：銷貨、進貨、車行名冊三種都不建立新批次。
        for kind, extra in (("operations", {"sheets": ["銷貨"]}), ("operations", {"sheets": ["進貨"]}), ("channels", {})):
            with self.subTest(kind=kind, extra=extra):
                upload = SimpleUploadedFile("new.xlsx", workbook_bytes(kind))
                self.assert_retired(self.client.post(reverse("legacy_import_list"),
                                                     {"import_type": kind, "source_file": upload, **extra}))
        self.assertEqual(LegacyImportBatch.objects.count(), 1)
        batch.refresh_from_db()
        self.assertEqual(batch.status, LegacyImportBatch.Status.PREVIEW)
        self.assertIsNone(batch.archived_at)
        self.assertTrue(batch.source_file)
        self.assertEqual(LegacyImportRow.objects.count(), rows_before)
        self.assertFalse(SalesOrder.objects.exists())

    def test_channel_roster_batch_urls_redirect_and_never_import(self):
        data = workbook_bytes("channels")
        upload = SimpleUploadedFile("roster.xlsx", data)
        batch = LegacyImportBatch.objects.create(
            import_type="channels", source_file=upload, original_filename=upload.name,
            file_sha256=file_sha256(upload), file_size=len(data), uploaded_by="tester",
        )
        build_import_preview(batch)
        sources_before = SalesSource.objects.count()
        self.assert_retired(self.client.get(reverse("legacy_import_detail", args=[batch.pk])))
        self.assert_retired(self.client.post(reverse("legacy_import_confirm", args=[batch.pk])))
        batch.refresh_from_db()
        self.assertEqual(batch.status, LegacyImportBatch.Status.PREVIEW)
        self.assertEqual(SalesSource.objects.count(), sources_before)

    def test_menus_maintenance_and_home_favorites_no_longer_link_to_the_import(self):
        old_url = reverse("legacy_import_list")
        for name in ("data_maintenance", "order_list", "dashboard"):
            with self.subTest(page=name):
                page = self.client.get(reverse(name))
                self.assertEqual(page.status_code, 200)
                self.assertNotContains(page, f'href="{old_url}"')
        self.assertNotIn("imports", LINKS)
        # 首頁的版本更新會提到「舊資料 Excel 匯入停用」，所以文字只檢查資料維護區。
        maintenance = self.client.get(reverse("data_maintenance"))
        self.assertNotContains(maintenance, "舊資料 Excel 匯入")
        self.assertContains(maintenance, "系統狀態檢查")

    def test_imported_orders_snapshot_batch_and_search_still_work(self):
        batch, order = self.imported_order()
        snapshot = LegacySalesSnapshot.objects.get(order=order)
        self.assertEqual(snapshot.vehicle_identifier, "ab-123")
        batch.refresh_from_db()
        self.assertEqual(batch.status, LegacyImportBatch.Status.COMPLETED)
        self.assertTrue(batch.rows.filter(pk=snapshot.import_row_id).exists())

        detail = self.client.get(reverse("order_detail", args=[order.pk]))
        self.assertEqual(detail.status_code, 200)
        # 頁首「引擎號碼／車身號碼」沒配車時顯示匯入時的車輛識別。
        self.assertContains(detail, '<strong class="order-hero-facts__mono">ab-123</strong>', html=False)
        self.assertContains(detail, "Excel 匯入")

        rebuild_order_search_index(order.pk)
        for query in ("AB-123", "ab123"):
            with self.subTest(query=query):
                found = self.client.get(reverse("order_list"), {"q": query, "tab": "all"})
                self.assertEqual(found.status_code, 200)
                self.assertContains(found, order.number)


@override_settings(LEGACY_IMPORT_UI_ENABLED=True)
class LegacyImportCodeKeptTests(LegacyImportRetiredTests):
    """匯入程式本身保留：測試開關打開時舊頁面仍能開（只給保留的舊測試用）。"""
    for _name in [name for name in dir(LegacyImportRetiredTests) if name.startswith("test_")]:
        locals()[_name] = None
    del _name

    def test_old_view_still_runs_behind_the_test_only_switch(self):
        page = self.client.get(reverse("legacy_import_list"))
        self.assertEqual(page.status_code, 200)
        self.assertTemplateUsed(page, "sales/legacy_import_list.html")
