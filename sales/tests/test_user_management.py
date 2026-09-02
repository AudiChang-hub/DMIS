from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import UserAccountAuditLog, UserSecurityProfile


class UserManagementTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="admin-manager",
            password="AdminPass!56789",
            first_name="管理者",
        )
        self.user = get_user_model().objects.create_user(
            username="sylvia",
            password="UserPass!56789",
            first_name="Sylvia",
        )

    def test_management_page_is_superuser_only_and_navigation_is_hidden(self):
        url = reverse("user_management")
        anonymous = self.client.get(url)
        self.assertRedirects(anonymous, f"{reverse('login')}?next={url}")

        self.client.force_login(self.user)
        forbidden = self.client.get(url)
        self.assertEqual(forbidden.status_code, 403)
        dashboard = self.client.get(reverse("data_maintenance"))
        self.assertNotContains(dashboard, reverse("user_management"))

        self.client.force_login(self.admin)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "帳號與權限")
        self.assertContains(response, "Sylvia")
        maintenance = self.client.get(reverse("data_maintenance"))
        self.assertContains(maintenance, reverse("user_management"))

    def test_admin_account_pages_render_and_help_points_to_account_topic(self):
        self.client.force_login(self.admin)
        pages = (
            reverse("user_account_create"),
            reverse("user_account_edit", args=[self.user.pk]),
            reverse("user_account_reset_password", args=[self.user.pk]),
        )
        for url in pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'{reverse("user_guide")}#account-management')

        guide = self.client.get(reverse("user_guide"))
        self.assertContains(guide, 'id="account-management"')
        self.assertContains(guide, "管理者看不到任何人的既有密碼")

    def test_password_reset_uses_padded_sections_for_long_account_name(self):
        self.user.first_name = "這是一個需要在窄螢幕完整顯示的很長使用者名稱"
        self.user.save(update_fields=["first_name"])
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("user_account_reset_password", args=[self.user.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.user.first_name)
        self.assertContains(response, 'class="account-form__section"', count=2)
        self.assertContains(response, "登入保護")
        self.assertContains(response, "確認重設密碼")

    def test_admin_can_create_account_with_hashed_temporary_password(self):
        self.client.force_login(self.admin)
        password = "TempPass!67890"
        response = self.client.post(
            reverse("user_account_create"),
            {
                "display_name": "王小明",
                "username": "wangming",
                "password1": password,
                "password2": password,
                "is_active": "on",
                "must_change_password": "on",
            },
        )
        self.assertRedirects(response, reverse("user_management"))
        account = get_user_model().objects.get(username="wangming")
        self.assertTrue(account.check_password(password))
        self.assertNotEqual(account.password, password)
        self.assertEqual(account.first_name, "王小明")
        self.assertTrue(account.is_active)
        self.assertFalse(account.is_superuser)
        self.assertTrue(account.security_profile.must_change_password)
        audit = UserAccountAuditLog.objects.get(
            target=account,
            action=UserAccountAuditLog.Action.CREATE,
        )
        self.assertNotIn(password, audit.description)
        self.assertNotIn(password, str(audit.metadata))

    def test_password_policy_accepts_eight_character_password_without_symbols(self):
        self.client.force_login(self.admin)
        password = "m7q4v2x9"

        response = self.client.post(
            reverse("user_account_create"),
            {
                "display_name": "短密碼測試",
                "username": "short-password-user",
                "password1": password,
                "password2": password,
                "is_active": "on",
            },
        )

        self.assertRedirects(response, reverse("user_management"))
        account = get_user_model().objects.get(username="short-password-user")
        self.assertTrue(account.check_password(password))

    def test_password_policy_rejects_password_shorter_than_eight_characters(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("user_account_create"),
            {
                "display_name": "過短密碼測試",
                "username": "too-short-password-user",
                "password1": "m7q4v2x",
                "password2": "m7q4v2x",
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "8 個字元")
        self.assertFalse(
            get_user_model().objects.filter(username="too-short-password-user").exists()
        )

    def test_password_pages_explain_the_simplified_policy(self):
        self.client.force_login(self.admin)

        create_page = self.client.get(reverse("user_account_create"))
        reset_page = self.client.get(
            reverse("user_account_reset_password", args=[self.user.pk])
        )

        for response in (create_page, reset_page):
            with self.subTest(path=response.request["PATH_INFO"]):
                self.assertContains(response, "密碼至少 8 碼")
                self.assertContains(response, "不強制符號或大小寫")

    def test_username_is_unique_without_case_difference(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("user_account_create"),
            {
                "display_name": "另一位",
                "username": "SYLVIA",
                "password1": "TempPass!67890",
                "password2": "TempPass!67890",
                "is_active": "on",
                "must_change_password": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "這個登入帳號已有人使用")
        self.assertEqual(get_user_model().objects.filter(username__iexact="sylvia").count(), 1)

    def test_admin_cannot_deactivate_or_demote_self(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("user_account_edit", args=[self.admin.pk]),
            {
                "display_name": "管理者",
                "username": self.admin.username,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "不能停用自己")
        self.assertContains(response, "不能移除自己目前的管理者權限")
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        self.assertTrue(self.admin.is_superuser)

    def test_system_keeps_at_least_one_active_superuser(self):
        other_admin = get_user_model().objects.create_superuser(
            username="second-admin",
            password="AdminPass!67890",
        )
        self.client.force_login(other_admin)
        self.admin.is_active = False
        self.admin.save(update_fields=["is_active"])

        response = self.client.post(
            reverse("user_account_status", args=[other_admin.pk]),
            {"action": "deactivate"},
        )
        self.assertRedirects(response, reverse("user_management"))
        other_admin.refresh_from_db()
        self.assertTrue(other_admin.is_active)

    def test_admin_can_deactivate_and_reactivate_another_account(self):
        self.client.force_login(self.admin)
        status_url = reverse("user_account_status", args=[self.user.pk])

        self.client.post(status_url, {"action": "deactivate"})
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertTrue(
            UserAccountAuditLog.objects.filter(
                target=self.user,
                action=UserAccountAuditLog.Action.DEACTIVATE,
            ).exists()
        )

        self.client.post(status_url, {"action": "activate"})
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_admin_can_quick_toggle_account_without_leaving_page(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("user_account_status", args=[self.user.pk]),
            {"active": "0"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["resource"], "user-account")
        self.assertFalse(response.json()["active"])
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_admin_quick_toggle_cannot_deactivate_self(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("user_account_status", args=[self.admin.pk]),
            {"active": "0"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_password_reset_forces_change_and_never_audits_plaintext(self):
        self.client.force_login(self.admin)
        new_password = "ResetPass!67890"
        response = self.client.post(
            reverse("user_account_reset_password", args=[self.user.pk]),
            {
                "password1": new_password,
                "password2": new_password,
                "must_change_password": "on",
            },
        )
        self.assertRedirects(response, reverse("user_management"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new_password))
        self.assertTrue(self.user.security_profile.must_change_password)
        audit = UserAccountAuditLog.objects.get(
            target=self.user,
            action=UserAccountAuditLog.Action.RESET_PASSWORD,
        )
        self.assertNotIn(new_password, audit.description)
        self.assertNotIn(new_password, str(audit.metadata))

    def test_password_reset_invalidates_existing_sessions(self):
        other_device = self.client_class()
        self.assertTrue(other_device.login(username="sylvia", password="UserPass!56789"))
        self.assertEqual(other_device.get(reverse("dashboard")).status_code, 200)

        self.client.force_login(self.admin)
        self.client.post(
            reverse("user_account_reset_password", args=[self.user.pk]),
            {
                "password1": "ResetPass!67890",
                "password2": "ResetPass!67890",
                "must_change_password": "on",
            },
        )

        response = other_device.get(reverse("dashboard"))
        self.assertRedirects(
            response,
            f'{reverse("login")}?next={reverse("dashboard")}',
        )

    def test_forced_password_change_blocks_other_pages_then_keeps_session(self):
        UserSecurityProfile.objects.create(user=self.user, must_change_password=True)
        self.client.force_login(self.user)

        blocked = self.client.get(reverse("dashboard"))
        self.assertRedirects(blocked, reverse("password_change_required"))
        change_page = self.client.get(reverse("password_change_required"))
        self.assertEqual(change_page.status_code, 200)
        self.assertContains(change_page, "首次登入，請先設定新密碼")

        new_password = "ChangedPass!67890"
        response = self.client.post(
            reverse("password_change_required"),
            {
                "old_password": "UserPass!56789",
                "new_password1": new_password,
                "new_password2": new_password,
            },
        )
        self.assertRedirects(response, reverse("dashboard"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new_password))
        self.assertFalse(self.user.security_profile.must_change_password)
        self.assertIsNotNone(self.user.security_profile.password_changed_at)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_list_supports_search_and_status_filter(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.client.force_login(self.admin)

        response = self.client.get(reverse("user_management"), {"q": "Syl", "status": "inactive"})
        self.assertContains(response, "Sylvia")
        self.assertNotContains(response, "管理者</h3>")
