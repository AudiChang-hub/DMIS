"""UAT U-09、U-10 方案 B（使用者 2026-11-06）。

U-09：沒有畫面權限紀錄的帳號在帳號管理標「尚未設定權限」並連到設定頁，完整性報告列出這些帳號。
U-10：匯入需要搭配淨利；匯入頁上傳前就說明並停用上傳（保留的舊匯入程式，測試開關下）。
T-244：舊 Excel 匯入停用後，權限頁拿掉「舊資料匯入與歷史修正」，舊網址登入即可導回。
"""
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.legacy_import_retired import RETIRED_MESSAGE
from sales.models import LegacyImportBatch


class AccessSetupHintTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.root = users.create_superuser("admin", password="Test-Only-123")
        cls.legacy = users.create_user("legacy_cli", password="Test-Only-123")
        cls.stock = users.create_user("stock", password="Test-Only-123")
        UserAccessState.objects.create(user=cls.stock, configured=True)
        for key in ("imports",):
            ScreenAccessGrant.objects.create(user=cls.stock, screen_key=key, view=True, operate=True)

    def test_user_management_marks_unconfigured_accounts_with_setup_link(self):
        self.client.force_login(self.root)
        html = self.client.get(reverse("user_management")).content.decode()
        legacy_row = html[html.index("@legacy_cli"):html.index("@legacy_cli") + 3000]
        self.assertIn("尚未設定權限", legacy_row)
        self.assertIn(f'{reverse("permission_workspace", args=[self.legacy.pk])}?tab=features', legacy_row)
        stock_row = html[html.index("@stock"):html.index("@stock") + 3000]
        self.assertNotIn("尚未設定權限", stock_row.split("account-row")[0])
        admin_row = html[html.index("@admin"):html.index("@admin") + 1500]
        self.assertNotIn("尚未設定權限", admin_row.split("account-row")[0])

    def test_integrity_report_lists_active_unconfigured_accounts(self):
        self.client.force_login(self.root)
        response = self.client.get(reverse("system_integrity_report"))
        self.assertContains(response, "1 個啟用中的帳號尚未設定畫面權限")
        self.assertContains(response, "@legacy_cli")
        self.legacy.is_active = False
        self.legacy.save()
        response = self.client.get(reverse("system_integrity_report"))
        self.assertContains(response, "所有啟用中的帳號都已設定畫面權限")

    def test_access_page_no_longer_offers_legacy_import_and_saving_drops_the_stale_grant(self):
        self.client.force_login(self.root)
        url = reverse("access_edit", args=[self.stock.pk])
        page = self.client.get(url, {"tab": "features"}, follow=True)
        self.assertNotContains(page, "舊資料匯入與歷史修正")
        self.assertNotContains(page, "screens.imports")
        # 舊的 imports 授權還在資料庫，但不影響其他項目；admin 儲存時只重建現有的畫面項目。
        preview = self.client.post(url, {"action": "preview", "version": "0", "screens.imports.view": "on",
                                         "screens.orders.view": "on"})
        self.assertEqual(preview.status_code, 200)
        self.client.post(url, {"action": "apply", "preview_token": preview.context["preview_token"]}, follow=True)
        self.assertFalse(ScreenAccessGrant.objects.filter(user=self.stock, screen_key="imports").exists())
        self.assertTrue(ScreenAccessGrant.objects.filter(user=self.stock, screen_key="orders", view=True).exists())

    def test_old_import_urls_redirect_for_any_signed_in_account(self):
        other = get_user_model().objects.create_user("no_imports", password="Test-Only-123")
        UserAccessState.objects.create(user=other, configured=True)
        ScreenAccessGrant.objects.create(user=other, screen_key="orders", view=True)
        for user in (self.stock, other, self.legacy):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                for method in (self.client.get, self.client.post):
                    response = method(reverse("legacy_import_list"))
                    self.assertRedirects(response, reverse("order_list"), fetch_redirect_response=False)
                    self.assertIn(RETIRED_MESSAGE, [str(m) for m in get_messages(response.wsgi_request)])

    @override_settings(LEGACY_IMPORT_UI_ENABLED=True)  # T-243：舊匯入畫面已停用，這裡測保留下來的程式
    def test_import_page_blocks_upload_before_creating_a_batch_without_profit(self):
        self.client.force_login(self.stock)
        page = self.client.get(reverse("legacy_import_list"))
        self.assertTrue(page.context["upload_blocked"])
        self.assertContains(page, "這個帳號還不能上傳")
        self.assertContains(page, 'type="submit" disabled aria-describedby="import-upload-blocked-reason"', html=False)
        upload = SimpleUploadedFile("fake.xlsx", b"PK\x03\x04", content_type="application/vnd.ms-excel")
        response = self.client.post(reverse("legacy_import_list"), {"import_type": "operations", "source_file": upload},
                                    follow=True)
        self.assertContains(response, "未上傳：這個帳號缺「查看淨利」權限")
        self.assertFalse(LegacyImportBatch.objects.exists())

        ScreenAccessGrant.objects.create(user=self.stock, screen_key="profit", view=True)
        page = self.client.get(reverse("legacy_import_list"))
        self.assertFalse(page.context["upload_blocked"])
        self.assertNotContains(page, "這個帳號還不能上傳")
