"""T-330：首頁「編輯常用功能」拿掉已廢除的「選車展示管理」。

已經存過這個選項的使用者照常打開首頁與編輯頁，畫面直接略過；說明頁與手冊不再提到它。資料全部虛構。
"""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.help.articles import ARTICLES
from sales.models import UserAppearancePreference
from sales.services.home_favorites import GROUPS, LINKS


class RetiredCatalogManageFavoriteTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("admin", password="Local-t330-271!")
        self.client.force_login(self.user)

    def test_catalog_manage_is_not_offered(self):
        self.assertNotIn("catalog-manage", LINKS)
        self.assertNotIn("catalog-manage", [key for *_, keys in GROUPS for key in keys])
        page = self.client.get(reverse("home_favorites"))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "選車展示管理")

    def test_saved_catalog_manage_is_skipped_without_error(self):
        UserAppearancePreference.objects.create(user=self.user, home_favorites=["catalog-manage", "orders", "help"])
        for name in ("dashboard", "home_favorites"):
            with self.subTest(name=name):
                page = self.client.get(reverse(name))
                self.assertEqual(page.status_code, 200)
                self.assertEqual(page.context["favorite_keys"], ["orders", "help"])
                self.assertNotContains(page, 'data-home-favorite="catalog-manage"')
                self.assertNotIn("選車展示管理", [link["label"] for link in page.context["favorite_links"]])
                self.assertNotIn("選車展示管理", [item["label"] for item in page.context["favorite_options"]])
        response = self.client.post(reverse("home_favorites"), {
            "favorite": ["orders", "help"], "order": "orders,help", "expected_version": 0,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(UserAppearancePreference.objects.get(user=self.user).home_favorites, ["orders", "help"])

    def test_help_and_manual_no_longer_mention_it(self):
        from sales.help.articles import TIPS
        texts = [f"{tip}" for tip in TIPS]
        texts += [f"{faq}" for article in ARTICLES for faq in getattr(article, "faqs", ())]
        self.assertFalse([text for text in texts if "選車展示管理" in text])
        manual = (Path(settings.BASE_DIR) / "docs/USER_MANUAL.md").read_text(encoding="utf-8")
        self.assertNotIn("選車展示管理", manual)
