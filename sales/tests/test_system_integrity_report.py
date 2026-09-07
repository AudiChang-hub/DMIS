from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch


class SystemIntegrityReportTests(TestCase):
    def test_restore_failure_is_not_styled_as_success(self):
        self.client.force_login(self.admin)
        with patch("sales.services.system_integrity.restore_drill_status", return_value={"label": "還原演練失敗", "success": False}):
            response = self.client.get(reverse("system_integrity_report"))
        self.assertContains(response, "integrity-restore--attention")
        self.assertContains(response, "還原演練失敗")

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="integrity-admin",
            password="AdminPass!56789",
        )
        self.user = get_user_model().objects.create_user(
            username="integrity-user",
            password="UserPass!56789",
        )

    def test_report_requires_an_active_superuser(self):
        url = reverse("system_integrity_report")

        anonymous = self.client.get(url)
        self.assertRedirects(anonymous, f"{reverse('login')}?next={url}")

        self.client.force_login(self.user)
        forbidden = self.client.get(url)
        self.assertEqual(forbidden.status_code, 403)
        self.assertContains(forbidden, "不能執行這個操作", status_code=403)

        self.client.force_login(self.admin)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "系統完整性報告")
        self.assertContains(response, "已知限制")
        self.assertContains(response, "2026-09-07.1")
        self.assertContains(response, "目前載入版本")
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_report_entry_is_hidden_from_regular_users(self):
        report_url = reverse("system_integrity_report")

        self.client.force_login(self.user)
        maintenance = self.client.get(reverse("data_maintenance"))
        self.assertNotContains(maintenance, report_url)
        self.assertNotContains(maintenance, "系統完整性報告")

        self.client.force_login(self.admin)
        maintenance = self.client.get(reverse("data_maintenance"))
        self.assertContains(maintenance, report_url)
        self.assertContains(maintenance, "系統完整性報告")

    def test_report_help_link_points_to_existing_topic(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("system_integrity_report"))
        self.assertContains(
            response,
            f'{reverse("user_guide")}#system-integrity',
        )

        guide = self.client.get(reverse("user_guide"))
        self.assertContains(guide, 'id="system-integrity"')

    def test_report_does_not_render_known_secret_or_customer_markers(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("system_integrity_report"))
        content = response.content.decode("utf-8")
        for forbidden in (
            "POSTGRES_PASSWORD=",
            "DJANGO_SECRET_KEY=",
            "CLOUDFLARE_TUNNEL_TOKEN=",
            "192.168.1.",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, content)
