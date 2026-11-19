"""T-243：銷貨、進貨的 Excel 匯入停用，車行／網路平台名冊匯入保留；已匯入的資料與相關功能照常。"""
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from sales.jobs import run_legacy_import_job
from sales.legacy_import_retired import RETIRED_MESSAGE
from sales.models import LegacyImportBatch, LegacyImportRow, LegacySalesSnapshot, SalesOrder, SalesSource, Store
from sales.services.home_favorites import LINKS
from sales.services.legacy_import import build_import_preview, confirm_import, file_sha256
from sales.services.order_search import rebuild_order_search_index
from sales.tests.test_legacy_import import workbook_bytes

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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

    def make_batch(self, kind="operations"):
        self.counter += 1
        data = workbook_bytes(kind)
        upload = SimpleUploadedFile(f"retired-{self.counter}.xlsx", data)
        batch = LegacyImportBatch.objects.create(
            import_type=kind, source_file=upload, original_filename=upload.name,
            file_sha256=file_sha256(upload), file_size=len(data), uploaded_by="tester",
        )
        build_import_preview(batch, sheets=["銷貨"] if kind == "operations" else None)
        return batch

    def upload(self, kind, **extra):
        data = {"import_type": kind, "source_file": SimpleUploadedFile("upload.xlsx", workbook_bytes(kind), content_type=XLSX),
                **extra}
        return self.client.post(reverse("legacy_import_list"), data)

    def assert_retired(self, response):
        self.assertRedirects(response, reverse("order_list"), fetch_redirect_response=False)
        self.assertIn(RETIRED_MESSAGE, [str(message) for message in get_messages(response.wsgi_request)])

    def test_sales_and_inventory_uploads_are_always_refused(self):
        for extra in ({"sheets": ["銷貨"]}, {"sheets": ["進貨"]}, {"sheets": ["銷貨", "進貨"]}, {}):
            with self.subTest(extra=extra):
                self.assert_retired(self.upload("operations", **extra))
        self.assert_retired(self.client.post(reverse("legacy_import_list"), {}))
        self.assertFalse(LegacyImportBatch.objects.exists())

    def test_old_operations_batch_urls_redirect_and_never_import(self):
        batch = self.make_batch()
        row = batch.rows.filter(sheet_name="銷貨").first()
        rows_before = LegacyImportRow.objects.count()
        pk = {"pk": batch.pk}
        row_kwargs = {**pk, "row_pk": row.pk}
        gets = [reverse("legacy_import_detail", kwargs=pk), reverse("legacy_import_status", kwargs=pk)]
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
        batch.refresh_from_db()
        self.assertEqual(batch.status, LegacyImportBatch.Status.PREVIEW)
        self.assertIsNone(batch.archived_at)
        self.assertTrue(batch.source_file)
        self.assertEqual(LegacyImportRow.objects.count(), rows_before)
        self.assertFalse(SalesOrder.objects.exists())

    @patch("sales.views.django_rq.get_queue")
    def test_channel_roster_import_still_works_end_to_end(self, get_queue):
        page = self.client.get(reverse("legacy_import_list"))
        self.assertEqual(page.status_code, 200)
        self.assertEqual(list(page.context["form"].fields["import_type"].choices), [("channels", "車行／網路平台名冊")])
        self.assertNotIn("sheets", page.context["form"].fields)
        self.assertContains(page, "車行名冊 Excel 匯入")

        response = self.upload("channels")
        batch = LegacyImportBatch.objects.get()
        self.assertEqual(batch.import_type, LegacyImportBatch.ImportType.CHANNELS)
        self.assertRedirects(response, reverse("legacy_import_detail", args=[batch.pk]))
        self.assertEqual(self.client.get(reverse("legacy_import_detail", args=[batch.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("legacy_import_status", args=[batch.pk])).status_code, 200)

        get_queue.return_value.enqueue.return_value.id = "job-roster"
        confirm = self.client.post(reverse("legacy_import_confirm", args=[batch.pk]))
        self.assertRedirects(confirm, reverse("legacy_import_detail", args=[batch.pk]))
        get_queue.return_value.enqueue.assert_called_once()
        run_legacy_import_job(str(batch.pk), "tester")
        batch.refresh_from_db()
        self.assertEqual(batch.status, LegacyImportBatch.Status.COMPLETED)
        self.assertTrue(SalesSource.objects.filter(name="測試車行").exists())

        # 名冊批次的封存／恢復照常；清單只列名冊批次。
        operations = self.make_batch()
        self.assertRedirects(self.client.post(reverse("legacy_import_archive", args=[batch.pk])), reverse("legacy_import_list"),
                             fetch_redirect_response=False)
        batch.refresh_from_db()
        self.assertIsNotNone(batch.archived_at)
        archived = self.client.get(reverse("legacy_import_list"), {"archived": "1"})
        self.assertEqual([item.pk for item in archived.context["batches"]], [batch.pk])
        self.client.post(reverse("legacy_import_restore", args=[batch.pk]))
        listed = self.client.get(reverse("legacy_import_list"))
        self.assertEqual([item.pk for item in listed.context["batches"]], [batch.pk])
        self.assertNotContains(listed, str(operations.pk))

    def test_roster_entry_is_still_reachable_from_menus_and_favorites(self):
        old_name = "舊資料 Excel 匯入"
        url = reverse("legacy_import_list")
        maintenance = self.client.get(reverse("data_maintenance"))
        self.assertContains(maintenance, f'href="{url}"', count=2)  # 頂部選單與資料維護區卡片
        self.assertContains(maintenance, "車行名冊 Excel 匯入")
        self.assertNotContains(maintenance, old_name)
        self.assertEqual(LINKS["imports"]["label"], "車行名冊 Excel 匯入")

    def test_imported_orders_snapshot_batch_and_search_still_work(self):
        batch = self.make_batch()
        confirm_import(batch, "tester")
        order = SalesOrder.objects.get(legacy_snapshot__isnull=False)
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
    """匯入程式本身保留：測試開關打開時營運匯入的舊頁面仍能開（只給保留的舊測試用）。"""
    for _name in [name for name in dir(LegacyImportRetiredTests) if name.startswith("test_")]:
        locals()[_name] = None
    del _name

    def test_operations_view_still_runs_behind_the_test_only_switch(self):
        page = self.client.get(reverse("legacy_import_list"))
        self.assertIn("sheets", page.context["form"].fields)
        batch = self.make_batch()
        self.assertEqual(self.client.get(reverse("legacy_import_detail", args=[batch.pk])).status_code, 200)
