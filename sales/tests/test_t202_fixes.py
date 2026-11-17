"""T-202 修正（v2.17.1）：表單過期的中文說明頁、平台表單不顯示沒有作用的「列入年節送禮」。

沒收備註改成真正選填的重現測試在 test_business_gates（例外結案）。
"""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from sales.models import SalesSource


class CsrfFailurePageTests(TestCase):
    """頁面停太久、表單的安全碼過期時，不再出現 Django 英文 403。"""

    def setUp(self):
        self.user = get_user_model().objects.create_user("t202-user", password="t202-pass-123")
        self.client = Client(enforce_csrf_checks=True)

    def assert_friendly(self, response):
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("CSRF verification failed", response.content.decode())
        self.assertContains(response, "頁面停留太久", status_code=403)
        self.assertContains(response, "請重新整理後再送一次", status_code=403)
        self.assertContains(response, "data-history-back", status_code=403)
        self.assertContains(response, f'href="{reverse("dashboard")}"', status_code=403)
        self.assertContains(response, 'class="card error-page"', status_code=403)

    def test_logged_in_form_post_without_token(self):
        self.client.force_login(self.user)
        self.assert_friendly(self.client.post(reverse("home_favorites"), {"favorites": ["orders"]}))

    def test_login_page_post_without_token(self):
        self.assert_friendly(self.client.post(reverse("login"), {"username": "t202-user", "password": "x"}))


class PlatformHolidayGiftFieldTests(TestCase):
    """網路平台不送年節禮：平台表單不顯示「列入年節送禮名單」，資料欄位保留不動；車行表單照舊。"""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", password="t202-pass-123")
        self.client.force_login(self.admin)

    def test_platform_form_has_no_holiday_gift_checkbox(self):
        page = self.client.get(reverse("sales_source_create") + "?kind=platform")
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'name="holiday_gift"')
        self.assertNotContains(page, "列入年節送禮")

    def test_dealer_form_keeps_holiday_gift_checkbox(self):
        page = self.client.get(reverse("sales_source_create") + "?kind=dealer")
        self.assertContains(page, 'name="holiday_gift"')

    def test_saving_platform_keeps_existing_holiday_gift_value(self):
        from sales.forms import SalesSourceForm
        platform = SalesSource.objects.create(source_type="platform", name="示範網路平台", holiday_gift=True)
        form = SalesSourceForm(instance=platform)
        self.assertNotIn("holiday_gift", form.fields)
        data = {name: form[name].value() or "" for name in form.fields}
        data.update({"name": "示範網路平台", "active": "on"})
        form = SalesSourceForm(data, instance=platform)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        platform.refresh_from_db()
        self.assertTrue(platform.holiday_gift)
