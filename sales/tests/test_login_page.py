from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse


class LoginPageTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_login_page_speaks_to_dealers_and_has_helpers(self):
        page = self.client.get(reverse("login")).content.decode()
        self.assertIn("車輛銷售管理平台</h1>", page)
        for point in ("選車看價", "線上下單", "查詢進度"):
            self.assertIn(f"<strong>{point}</strong>", page)
        self.assertNotIn("店內人員", page)
        self.assertIn("data-password-toggle", page)
        self.assertIn("data-caps-warning", page)
        self.assertIn("連續輸入錯誤 5 次會暫停登入 15 分鐘", page)
        self.assertIn(reverse("catalog"), page)
        self.assertIn("css/login.css", page)

    def test_wrong_password_shows_alert_and_keeps_layout(self):
        get_user_model().objects.create_user("clerk", password="Correct-pass-925!")
        response = self.client.post(reverse("login"), {"username": "clerk", "password": "wrong"})
        self.assertContains(response, 'class="login-alert" role="alert"')
        self.assertContains(response, "login-showcase")
