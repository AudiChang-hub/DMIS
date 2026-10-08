"""本人近期驗證：閒置 10 分鐘才鎖、最長 8 小時；真人操作才延長，過期不能復活。"""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.services.profit_access import IDLE_SECONDS, MAX_SECONDS, SESSION_KEY

PASSWORD = "Unlock-test-730!"


class UnlockSessionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user("clerk", password=PASSWORD)
        UserAccessState.objects.create(user=self.user, configured=True)
        ScreenAccessGrant.objects.create(user=self.user, screen_key="profit", view=True, export=True)
        ScreenAccessGrant.objects.create(user=self.user, screen_key="orders", view=True)
        self.client.force_login(self.user)

    def unlock(self):
        return self.client.post(reverse("profit_unlock"), {"password": PASSWORD, "next": reverse("order_list")})

    def token(self):
        return dict(self.client.session[SESSION_KEY])

    def set_token(self, **changes):
        session = self.client.session
        token = dict(session[SESSION_KEY])
        token.update(changes)
        session[SESSION_KEY] = token
        session.save()

    def now(self):
        return timezone.now().timestamp()

    def test_unlock_sets_ten_minute_idle_window_and_eight_hour_cap(self):
        self.assertEqual((IDLE_SECONDS, MAX_SECONDS), (600, 28800))
        before = self.now()
        self.unlock()
        token = self.token()
        self.assertAlmostEqual(token["until"] - before, 600, delta=5)
        self.assertAlmostEqual(token["max_until"] - before, 28800, delta=5)

    def test_real_activity_extends_the_idle_window(self):
        self.unlock()
        self.set_token(until=self.now() + 30)
        response = self.client.post(reverse("unlock_touch"))
        self.assertEqual(response.status_code, 200)
        self.assertAlmostEqual(self.token()["until"], self.now() + 600, delta=5)
        self.assertEqual(response.json()["until"], int(self.token()["until"] * 1000))

    def test_extension_never_passes_the_eight_hour_cap(self):
        self.unlock()
        cap = self.now() + 120
        self.set_token(until=self.now() + 30, max_until=cap)
        self.client.post(reverse("unlock_touch"))
        self.assertAlmostEqual(self.token()["until"], cap, delta=1)
        self.set_token(until=cap - 1)
        self.client.post(reverse("unlock_touch"))
        self.assertAlmostEqual(self.token()["until"], cap, delta=1)  # 到頂後不再往後

    def test_expired_unlock_cannot_be_revived(self):
        self.unlock()
        self.set_token(until=self.now() - 1)
        response = self.client.post(reverse("unlock_touch"))
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.json()["locked"])
        self.assertLess(self.token()["until"], self.now())
        self.assertEqual(self.client.get(reverse("unlock_touch")).status_code, 409)
        order_list = self.client.get(reverse("order_list"))
        self.assertContains(order_list, "輸入密碼查看")

    def test_status_check_does_not_extend(self):
        self.unlock()
        original = self.now() + 45
        self.set_token(until=original)
        response = self.client.get(reverse("unlock_touch"))
        self.assertEqual(response.status_code, 200)
        self.assertAlmostEqual(self.token()["until"], original, delta=0.01)

    def test_old_style_unlock_without_cap_is_not_extended(self):
        self.unlock()
        session = self.client.session
        token = dict(session[SESSION_KEY])
        token.pop("max_until")
        token["until"] = self.now() + 30
        session[SESSION_KEY] = token
        session.save()
        self.client.post(reverse("unlock_touch"))
        self.assertAlmostEqual(self.token()["until"], token["until"], delta=0.01)

    def test_access_change_invalidates_the_unlock(self):
        self.unlock()
        UserAccessState.objects.filter(user=self.user).update(version=9)
        self.assertEqual(self.client.post(reverse("unlock_touch")).status_code, 409)

    def test_password_change_invalidates_the_unlock(self):
        self.unlock()
        self.user.set_password("Another-pass-731!")
        self.user.save()
        self.client.force_login(self.user)  # 改密碼後重新登入，舊的解鎖不能沿用
        self.assertEqual(self.client.post(reverse("unlock_touch")).status_code, 409)

    def test_manual_lock_clears_everything(self):
        self.unlock()
        self.client.post(reverse("profit_lock"))
        self.assertEqual(self.client.post(reverse("unlock_touch")).status_code, 409)

    def test_pages_only_carry_touch_settings_while_unlocked(self):
        locked = self.client.get(reverse("order_list"))
        self.assertNotContains(locked, "data-unlock-touch-url")
        self.unlock()
        unlocked = self.client.get(reverse("order_list"))
        self.assertContains(unlocked, f'data-unlock-touch-url="{reverse("unlock_touch")}"')
        self.assertContains(unlocked, "閒置 10 分鐘自動鎖定")

    def test_touch_requires_login_and_post_needs_csrf(self):
        anonymous = self.client_class()
        self.assertEqual(anonymous.post(reverse("unlock_touch")).status_code, 302)
        strict = self.client_class(enforce_csrf_checks=True)
        strict.force_login(self.user)
        self.assertEqual(strict.post(reverse("unlock_touch")).status_code, 403)
