from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from config.middleware import RequestIdMiddleware
from sales import views


class ProductExperienceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="guide-user",
            password="test-pass-123",
        )

    def test_user_guide_requires_login_and_is_task_oriented(self):
        response = self.client.get(reverse("user_guide"))
        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('user_guide')}",
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("user_guide"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "現在想做什麼？從任務開始找")
        self.assertContains(response, 'data-guide-search')
        self.assertContains(response, 'id="create-order"')
        self.assertContains(response, 'id="ocr"')
        self.assertContains(response, 'id="inventory"')
        self.assertContains(response, 'id="troubleshooting"')
        self.assertContains(response, "LicenseWatcher 尚未啟用")
        self.assertContains(response, 'data-print-guide')

    def test_navigation_opens_context_help_without_leaving_work(self):
        self.client.force_login(self.user)

        dashboard = self.client.get(reverse("dashboard"))
        self.assertContains(dashboard, f'{reverse("user_guide")}#dashboard')
        self.assertContains(dashboard, 'target="_blank"')
        self.assertContains(dashboard, "不會離開目前資料")

        inventory = self.client.get(reverse("inventory_list"))
        self.assertContains(inventory, f'{reverse("user_guide")}#inventory')

    def test_every_response_has_non_sensitive_request_id(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        request_id = response.headers.get("X-Request-ID")
        self.assertRegex(request_id, r"^[A-F0-9]{12}$")

    def test_health_endpoint_is_minimal_and_does_not_require_login(self):
        response = self.client.get(reverse("system_health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

    def test_error_pages_use_plain_language_and_support_reference(self):
        request = RequestFactory().get("/missing/")
        request.user = AnonymousUser()
        request.request_id = "ABCDEF123456"

        not_found = views.page_not_found(request)
        self.assertEqual(not_found.status_code, 404)
        self.assertIn("找不到你要開啟的頁面", not_found.content.decode())

        server_error = views.server_error(request)
        body = server_error.content.decode()
        self.assertEqual(server_error.status_code, 500)
        self.assertIn("ABCDEF123456", body)
        self.assertIn("這不是你的操作問題", body)

    def test_request_id_middleware_marks_failures(self):
        middleware = RequestIdMiddleware(lambda request: HttpResponse(status=500))
        response = middleware(RequestFactory().get("/broken/"))
        self.assertRegex(response["X-Request-ID"], r"^[A-F0-9]{12}$")

    def test_common_ux_scripts_include_recovery_controls(self):
        feedback = Path("static/js/form-feedback.js").read_text(encoding="utf-8")
        connectivity = Path("static/js/connectivity-status.js").read_text(
            encoding="utf-8"
        )
        base = Path("templates/base.html").read_text(encoding="utf-8")

        self.assertIn("dataset.formErrorSummary", feedback)
        self.assertIn("還有 ${result.items.length} 個地方需要確認", feedback)
        self.assertIn("請先上傳證件正反面", feedback)
        self.assertIn("dataset.submitting", feedback)
        self.assertIn("資料正在處理，請不要重複送出", feedback)
        self.assertIn('window.addEventListener("offline"', connectivity)
        self.assertIn("尚未送出的內容可能還沒同步", base)

    def test_login_is_temporarily_throttled_after_repeated_failures(self):
        login_url = reverse("login")
        for _ in range(4):
            response = self.client.post(
                login_url,
                {"username": self.user.username, "password": "wrong-password"},
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.post(
            login_url,
            {"username": self.user.username, "password": "wrong-password"},
        )
        self.assertContains(response, "帳號已暫停嘗試 15 分鐘")

        response = self.client.post(
            login_url,
            {"username": self.user.username, "password": "test-pass-123"},
        )
        self.assertContains(response, "請 15 分鐘後再試")

        cache.clear()
        response = self.client.post(
            login_url,
            {"username": self.user.username, "password": "test-pass-123"},
        )
        self.assertRedirects(response, reverse("dashboard"))

    def test_admin_login_cannot_bypass_the_same_throttle(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        admin_login_url = reverse("admin:login")

        for _ in range(5):
            response = self.client.post(
                admin_login_url,
                {"username": self.user.username, "password": "wrong-password"},
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.post(
            admin_login_url,
            {"username": self.user.username, "password": "test-pass-123"},
        )
        self.assertContains(response, "請 15 分鐘後再試")


class UserDocumentationTests(TestCase):
    def test_end_user_manual_is_current_django_workflow(self):
        manual = Path("docs/USER_MANUAL.md").read_text(encoding="utf-8")
        self.assertIn("戰情首頁與全欄位搜尋", manual)
        self.assertIn("訂單建立後怎麼做", manual)
        self.assertIn("營運、淨利與對帳", manual)
        self.assertNotIn("Odoo 16", manual)
        self.assertNotIn("8069", manual)
