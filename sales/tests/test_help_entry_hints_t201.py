"""T-201 入口提示：首頁新手卡片（b）、功能頁頁首「這頁做什麼」（c）。

只動首頁與套表列印、報表中心、資料維護區這幾頁；共用的 site_navigation、返回列與其他頁面不變。
"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.help import BY_SLUG, PAGE_TIPS

TEMPLATES = Path(settings.BASE_DIR) / "templates"
TIP_TEMPLATES = {"sales/form_print.html", "sales/data_maintenance.html", "sales/reporting/display.html"}


class EntryHintSourceTests(SimpleTestCase):
    def test_page_tips_point_to_existing_articles_and_real_routes(self):
        self.assertEqual(set(PAGE_TIPS), {"form_print", "report_center", "report_display", "data_maintenance"})
        for route, tip in PAGE_TIPS.items():
            with self.subTest(route=route):
                self.assertIn(tip.article, BY_SLUG)
                self.assertTrue(tip.does.strip())
                reverse(route, args=[1]) if route == "report_display" else reverse(route)

    def test_only_the_three_function_pages_carry_the_tip(self):
        """鎖住影響範圍：頁首提示只放在這三個模板，首頁卡片只放在首頁。"""
        tips, cards = set(), set()
        for path in TEMPLATES.rglob("*.html"):
            text = path.read_text(encoding="utf-8")
            name = path.relative_to(TEMPLATES).as_posix()
            if re.search(r"{%\s*help_page_tip\s*%}", text):
                tips.add(name)
            if re.search(r"{%\s*help_start_card\s*%}", text):
                cards.add(name)
        self.assertEqual(tips, TIP_TEMPLATES)
        self.assertEqual(cards, {"sales/dashboard.html"})

    def test_shared_navigation_is_untouched(self):
        """site_navigation 與返回列不帶任何說明提示（其他頁面版面不變）。"""
        for name in ("sales/_page_back.html", "base.html"):
            text = (TEMPLATES / name).read_text(encoding="utf-8")
            self.assertNotIn("help_page_tip", text)
            self.assertNotIn("help_start_card", text)
        source = (Path(settings.BASE_DIR) / "sales" / "templatetags" / "site_copy.py").read_text(encoding="utf-8")
        self.assertNotIn("page_tip", source)

    def test_start_card_storage_is_guarded(self):
        script = (Path(settings.BASE_DIR) / "static" / "js" / "help-start-card.js").read_text(encoding="utf-8")
        self.assertEqual(script.count("window.localStorage"), 2)
        self.assertEqual(script.count("try {"), 2)
        self.assertIn("card.hidden = false", script)


class EntryHintPageTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", password="t201-pass")
        self.client.force_login(self.admin)

    def test_dashboard_shows_dismissible_start_card_hidden_until_script_checks_storage(self):
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, "data-help-start-card hidden")
        self.assertContains(page, f'href="{reverse("help_start")}"')
        self.assertContains(page, "第一次用？")
        self.assertContains(page, "data-help-start-close")
        self.assertContains(page, "js/help-start-card.js")
        body = page.content.decode()
        self.assertLess(body.index("home-hero"), body.index("data-help-start-card"))
        self.assertLess(body.index("data-help-start-card"), body.index("home-tasks"))

    def test_function_pages_show_what_the_page_does_and_link_the_article(self):
        for route, slug in (("form_print", "form-print"), ("data_maintenance", "rebuild")):
            with self.subTest(route=route):
                page = self.client.get(reverse(route))
                self.assertContains(page, "data-page-help-tip")
                self.assertContains(page, "這頁做什麼")
                self.assertContains(page, f'href="{reverse("help_article", args=[slug])}"')
                self.assertContains(page, PAGE_TIPS[route].does)

    def test_other_pages_do_not_get_the_tip(self):
        for route in ("order_list", "inventory_list", "operations_report", "vehicle_model_list", "dashboard"):
            with self.subTest(route=route):
                self.assertNotContains(self.client.get(reverse(route)), "data-page-help-tip")

    def test_staff_without_the_article_sees_no_tip_and_no_card(self):
        staff = get_user_model().objects.create_user("t201-staff", password="t201-pass")
        UserAccessState.objects.create(user=staff, configured=True)
        ScreenAccessGrant.objects.create(user=staff, screen_key="dashboard", view=True)
        self.client.force_login(staff)
        page = self.client.get(reverse("dashboard"))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "data-help-start-card")
