from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import UserAppearancePreference
from sales.services.home_favorites import DEFAULT_KEYS, GROUPS, LINKS


class HomeFavoritesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("favorites-user", password="test-only")
        cls.other = get_user_model().objects.create_user("favorites-other", password="test-only")

    def setUp(self):
        self.client.force_login(self.user)

    def save(self, keys, version=0, **extra):
        return self.client.post(reverse("home_favorites"), {"favorite": keys, "order": ",".join(keys), "expected_version": version, **extra})

    def test_catalog_has_unique_keys_and_real_routes(self):
        grouped = [key for _, _, _, keys in GROUPS for key in keys]
        self.assertEqual(len(grouped), len(set(grouped)))
        self.assertEqual(set(grouped), set(LINKS))
        for item in LINKS.values():
            self.assertTrue(reverse(item["route"]))

    def test_get_is_read_only_and_defaults_are_permission_filtered(self):
        response = self.client.get(reverse("home_favorites"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["favorite_keys"], list(DEFAULT_KEYS))
        self.assertFalse(UserAppearancePreference.objects.filter(user=self.user).exists())
        self.assertNotContains(response, 'value="announcements"')
        self.assertNotContains(response, 'value="report-design"')
        self.assertContains(response, "搜尋功能")
        self.assertContains(response, "首頁顯示預覽")
        self.assertContains(response, "編輯常用功能")
        self.assertContains(response, "儲存常用功能")
        self.assertNotContains(response, "我的最愛")
        home = self.client.get(reverse("dashboard"))
        self.assertContains(home, '<h2 id="home-favorites-title">常用功能</h2>', html=True)
        self.assertContains(home, "編輯常用功能")

    def test_save_order_and_account_isolation(self):
        response = self.save(["inventory", "orders", "help"], user_id=self.other.pk, next="https://example.com/")
        self.assertRedirects(response, reverse("dashboard"))
        preference = UserAppearancePreference.objects.get(user=self.user)
        self.assertEqual(preference.home_favorites, ["inventory", "orders", "help"])
        self.assertEqual(preference.home_favorites_version, 1)
        page = self.client.get(reverse("dashboard"))
        self.assertEqual([x["key"] for x in page.context["favorite_links"]], preference.home_favorites)
        other_client = Client()
        other_client.force_login(self.other)
        self.assertEqual(other_client.get(reverse("dashboard")).context["favorite_keys"], list(DEFAULT_KEYS))
        self.assertFalse(UserAppearancePreference.objects.filter(user=self.other).exists())

    def test_same_account_another_device_loads_saved_favorites(self):
        self.save(["help", "orders"])
        other_device = Client()
        other_device.force_login(self.user)
        self.assertEqual(other_device.get(reverse("home_favorites")).context["favorite_keys"], ["help", "orders"])

    def test_empty_list_stays_empty_without_default_fallback(self):
        self.assertEqual(self.save([]).status_code, 302)
        for name in ("dashboard", "home_favorites"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.context["favorite_keys"], [])
        self.assertContains(self.client.get(reverse("dashboard")), "目前沒有可顯示的常用功能")

    def test_default_initialization_preserves_existing_mobile_links_and_theme(self):
        preference = UserAppearancePreference.objects.create(user=self.user, mobile_quick_links=["inventory", "customers"], theme="night-blue")
        self.assertEqual(self.client.get(reverse("home_favorites")).context["favorite_keys"], [*DEFAULT_KEYS, "inventory", "customers"])
        self.save(["help"])
        preference.refresh_from_db()
        self.assertEqual(preference.mobile_quick_links, ["inventory", "customers"])
        self.assertEqual(preference.theme, "night-blue")

    def test_invalid_duplicate_unauthorized_and_external_keys_do_not_write(self):
        for keys in (["help", "help"], ["unknown"], ["https://example.com/"], ["announcements"]):
            with self.subTest(keys=keys):
                self.assertEqual(self.save(keys).status_code, 400)
                self.assertFalse(UserAppearancePreference.objects.filter(user=self.user).exists())

    def test_order_mismatch_is_rejected(self):
        self.assertEqual(self.save(["orders"], order="help").status_code, 400)
        self.assertFalse(UserAppearancePreference.objects.filter(user=self.user).exists())

    def test_missing_version_is_rejected(self):
        response = self.client.post(reverse("home_favorites"), {"favorite": ["help"]})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(UserAppearancePreference.objects.filter(user=self.user).exists())

    def test_stale_window_does_not_overwrite_and_can_confirm_latest(self):
        self.save(["help"])
        stale = self.save(["inventory"])
        self.assertEqual(stale.status_code, 409)
        self.assertContains(stale, "本次未覆寫", status_code=409)
        self.assertEqual(stale.context["favorite_keys"], ["help"])
        self.assertEqual(stale.context["favorite_version"], 1)
        self.assertEqual(self.save(["inventory"], version=1).status_code, 302)
        self.assertEqual(UserAppearancePreference.objects.get(user=self.user).home_favorites, ["inventory"])

    def test_view_only_permissions_do_not_expose_create_shortcut(self):
        UserAccessState.objects.create(user=self.user, configured=True)
        ScreenAccessGrant.objects.create(user=self.user, screen_key="orders", view=True, operate=False)
        response = self.client.get(reverse("home_favorites"))
        self.assertContains(response, 'value="orders"')
        self.assertNotContains(response, 'value="new-order"')
        self.assertEqual(self.save(["new-order"]).status_code, 400)

    def test_revoked_favorite_is_hidden_and_cannot_be_resaved(self):
        UserAccessState.objects.create(user=self.user, configured=True)
        grant = ScreenAccessGrant.objects.create(user=self.user, screen_key="inventory", view=True)
        self.save(["inventory", "help"])
        grant.delete()
        page = self.client.get(reverse("dashboard"))
        self.assertEqual(page.context["favorite_keys"], ["help"])
        self.assertNotContains(page, 'data-home-favorite="inventory"')
        self.assertEqual(self.save(["inventory"], version=1).status_code, 400)
        self.assertEqual(UserAppearancePreference.objects.get(user=self.user).home_favorites, ["inventory", "help"])

    def test_no_javascript_post_preserves_order_and_appends_new(self):
        self.save(["help", "orders"])
        self.assertEqual(self.save(["orders", "inventory", "help"], version=1, order="").status_code, 302)
        self.assertEqual(UserAppearancePreference.objects.get(user=self.user).home_favorites, ["help", "orders", "inventory"])

    def test_login_csrf_and_methods_are_enforced(self):
        self.assertEqual(Client().get(reverse("home_favorites")).status_code, 302)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(reverse("home_favorites"), {"expected_version": 0}).status_code, 403)
        self.assertEqual(self.client.delete(reverse("home_favorites")).status_code, 405)

    def test_restore_defaults_can_be_saved_after_clear(self):
        self.save([])
        defaults = self.client.get(reverse("home_favorites")).context["favorite_defaults"]
        self.assertEqual(self.save(defaults, version=1).status_code, 302)
        self.assertEqual(UserAppearancePreference.objects.get(user=self.user).home_favorites, list(DEFAULT_KEYS))
