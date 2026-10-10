from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import LegacyImportBatch, OrderEvent, SalesOrder, Store, UserAccountAuditLog
from sales.services.legacy_import import build_import_preview, confirm_import, file_sha256
from django.utils import timezone

from sales.services.order_workspace import mask_account
from sales.services.profit_access import SESSION_KEY
from sales.tests.test_legacy_import import workbook_bytes

FULL_ACCOUNT = "299540972331"
BANK = "中國信託基隆分行"


class MaskAccountTests(SimpleTestCase):
    def test_only_last_four_digits_are_visible(self):
        self.assertEqual(mask_account(FULL_ACCOUNT), "●●●●2331")
        self.assertEqual(mask_account("00113990812591"), "●●●●2591")  # 帳號長度不外洩
        self.assertEqual(mask_account("1234"), "●●●●")
        self.assertEqual(mask_account("12"), "●●●●")
        self.assertEqual(mask_account(""), "")
        self.assertEqual(mask_account(None), "")


class PayoutAccountVisibilityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.temp = TemporaryDirectory()
        override = override_settings(MEDIA_ROOT=self.temp.name)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(self.temp.cleanup)
        Store.objects.create(name="總店", code="MAIN")
        workbook = load_workbook(BytesIO(workbook_bytes()))
        sales = workbook["銷貨"]
        sales["BF4"], sales["BG4"] = FULL_ACCOUNT, BANK
        stream = BytesIO()
        workbook.save(stream)
        upload = SimpleUploadedFile("payout.xlsx", stream.getvalue())
        batch = LegacyImportBatch.objects.create(
            import_type="operations", source_file=upload, original_filename="payout.xlsx",
            file_sha256=file_sha256(upload), file_size=len(stream.getvalue()),
        )
        build_import_preview(batch)
        confirm_import(batch, "tester")
        self.order = SalesOrder.objects.get()
        self.assertEqual(self.order.operations.remittance_account, FULL_ACCOUNT)

    def make_user(self, name, **grants):
        user = get_user_model().objects.create_user(name, password="Test-Only-123")
        UserAccessState.objects.create(user=user, configured=True)
        for key, (view, operate) in grants.items():
            ScreenAccessGrant.objects.create(user=user, screen_key=key, view=view, operate=operate)
        return user

    def subsidy_page(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("order_detail", args=[self.order.pk]), {"tab": "subsidy"})

    def test_order_work_user_sees_bank_and_masked_account_read_only(self):
        user = self.make_user("worker", orders=(True, True), work=(True, True))
        response = self.subsidy_page(user)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "撥款銀行與匯款帳戶")
        self.assertContains(response, BANK)
        # 1.62.4 起有訂單作業權限者直接看到完整帳號（使用者 2026-10-10）。
        self.assertContains(response, FULL_ACCOUNT)
        self.assertNotContains(response, "●●●●2331")
        self.assertNotContains(response, 'name="operations-remittance_account"')

    def test_reveal_requires_own_password_then_returns_full_account_and_audits(self):
        user = self.make_user("worker", orders=(True, True), work=(True, True))
        self.client.force_login(user)
        url = reverse("order_payout_reveal", args=[self.order.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        for payload, status in (({}, 401), ({"password": ""}, 401), ({"password": "wrong-password"}, 400)):
            denied = self.client.post(url, payload)
            self.assertEqual(denied.status_code, status)
            self.assertFalse(denied.json()["ok"])
            self.assertEqual(denied.json().get("need_password", False), status == 401)
            self.assertNotIn(FULL_ACCOUNT, denied.content.decode())
        self.assertFalse(OrderEvent.objects.filter(event_type="payout_account_viewed").exists())
        self.assertTrue(UserAccountAuditLog.objects.filter(
            actor=user, description__contains="密碼驗證失敗").exists())
        response = self.client.post(url, {"password": "Test-Only-123"})
        self.assertEqual(response.json(), {"ok": True, "value": FULL_ACCOUNT})
        event = OrderEvent.objects.get(order=self.order, event_type="payout_account_viewed")
        self.assertEqual(event.actor_name, "worker")

    def test_after_one_password_reveals_need_no_password_until_idle_expiry(self):
        user = self.make_user("worker", orders=(True, True), work=(True, True))
        self.client.force_login(user)
        url = reverse("order_payout_reveal", args=[self.order.pk])
        self.assertEqual(self.client.post(url, {"password": "Test-Only-123"}).status_code, 200)
        # 驗證有效期間：免再輸入，但每次顯示仍留下查看紀錄
        self.assertEqual(self.client.post(url).json(), {"ok": True, "value": FULL_ACCOUNT})
        self.assertEqual(OrderEvent.objects.filter(event_type="payout_account_viewed").count(), 2)
        # 閒置到期：回到要輸入密碼
        session = self.client.session
        token = session[SESSION_KEY]
        token["until"] = timezone.now().timestamp() - 1
        session[SESSION_KEY] = token
        session.save()
        expired = self.client.post(url)
        self.assertEqual(expired.status_code, 401)
        self.assertTrue(expired.json()["need_password"])
        # 立即鎖定也會讓下一次顯示重新要密碼
        self.assertEqual(self.client.post(url, {"password": "Test-Only-123"}).status_code, 200)
        self.client.post(reverse("profit_lock"))
        self.assertEqual(self.client.post(url).status_code, 401)

    def test_wrong_passwords_are_rate_limited_even_if_the_next_one_is_correct(self):
        user = self.make_user("worker", orders=(True, True), work=(True, True))
        self.client.force_login(user)
        url = reverse("order_payout_reveal", args=[self.order.pk])
        for _ in range(5):
            self.assertEqual(self.client.post(url, {"password": "wrong-password"}).status_code, 400)
        blocked = self.client.post(url, {"password": "Test-Only-123"})
        self.assertEqual(blocked.status_code, 429)
        self.assertNotIn(FULL_ACCOUNT, blocked.content.decode())
        self.assertFalse(OrderEvent.objects.filter(event_type="payout_account_viewed").exists())

    def test_finance_user_keeps_the_editable_form_not_the_read_only_block(self):
        user = self.make_user(
            "finance", orders=(True, True), work=(True, True), order_finance=(True, True),
        )
        response = self.subsidy_page(user)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "撥款銀行與匯款帳戶")
        self.assertContains(response, 'name="operations-remittance_account"')

    def test_user_without_order_work_cannot_see_or_reveal(self):
        user = self.make_user("viewer", orders=(True, False))
        response = self.subsidy_page(user)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "撥款銀行與匯款帳戶")
        self.assertNotContains(response, FULL_ACCOUNT)
        reveal = self.client.post(reverse("order_payout_reveal", args=[self.order.pk]), {"password": "Test-Only-123"})
        self.assertEqual(reveal.status_code, 403)
        self.assertFalse(OrderEvent.objects.filter(event_type="payout_account_viewed").exists())

    def test_work_user_with_view_only_cannot_reveal(self):
        user = self.make_user("looker", orders=(True, True), work=(True, False))
        self.client.force_login(user)
        response = self.client.post(reverse("order_payout_reveal", args=[self.order.pk]), {"password": "Test-Only-123"})
        self.assertEqual(response.status_code, 403)
        page = self.subsidy_page(user)
        self.assertNotContains(page, "撥款銀行與匯款帳戶")
