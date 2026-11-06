"""UAT U-09、U-10 方案 B（使用者 2026-11-06）。

U-09：沒有畫面權限紀錄的帳號在帳號管理標「尚未設定權限」並連到設定頁，完整性報告列出這些帳號。
U-10：匯入需要搭配淨利。權限頁註明、只勾匯入沒勾淨利時預覽與套用都提醒；匯入頁上傳前就說明並停用上傳。
"""
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.access.views import IMPORT_WITHOUT_PROFIT
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

    def test_access_page_explains_and_warns_import_without_profit(self):
        self.client.force_login(self.root)
        url = reverse("access_edit", args=[self.stock.pk])
        page = self.client.get(url, {"tab": "features"}, follow=True)
        self.assertContains(page, "需同時勾選「查看淨利」才能完成匯入")
        preview = self.client.post(url, {"action": "preview", "version": "0", "screens.imports.view": "on"})
        self.assertContains(preview, IMPORT_WITHOUT_PROFIT)
        both = self.client.post(url, {"action": "preview", "version": "0", "screens.imports.view": "on",
                                      "screens.profit.view": "on"})
        self.assertNotContains(both, IMPORT_WITHOUT_PROFIT)
        applied = self.client.post(url, {"action": "apply", "preview_token": preview.context["preview_token"]}, follow=True)
        self.assertContains(applied, "畫面權限已套用")
        self.assertContains(applied, IMPORT_WITHOUT_PROFIT)

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
