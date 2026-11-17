"""T-214（使用者 2026-11-17）：訂單頁往下捲時，精簡列最左邊也能返回列表，與麵包屑同一目的地。"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from sales.tests import test_order_flow as flow


def compact_bar(page):
    start = page.index("data-order-compact-bar")
    return page[start:page.index("data-order-stage-start", start)]


class OrderCompactBackLinkTests(TestCase):
    setUp = flow.OrderFlowTests.setUp
    make_order = flow.OrderFlowTests.make_order

    def page(self, order, query=""):
        admin = get_user_model().objects.filter(username="admin").first() or get_user_model().objects.create_superuser(
            "admin", password="test-only")
        self.client.force_login(admin)
        response = self.client.get(reverse("order_detail", args=[order.pk]) + query)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_compact_bar_starts_with_back_link_matching_breadcrumb(self):
        page = self.page(self.make_order())
        list_url = reverse("order_list")
        crumb = re.search(r'<a class="back-link" href="([^"]+)" data-return-to aria-label="([^"]+)"', page)
        self.assertEqual(crumb.groups(), (list_url, "回到全部訂單"))
        bar = compact_bar(page)
        first = re.search(r"<(\w+)[^>]*>", bar[bar.index(">") + 1:])
        self.assertEqual(first.group(1), "a")
        back = re.search(r'<a class="order-compact-bar__back" href="([^"]+)" data-return-to aria-label="([^"]+)">', bar)
        self.assertIsNotNone(back)
        # 目的地（fallback）與無障礙名稱都和麵包屑一致；篩選與捲動位置交給同一套 data-return-to。
        self.assertEqual(back.groups(), crumb.groups())
        self.assertIn('aria-hidden="true">←</span>', bar)

    def test_compact_bar_keeps_existing_content(self):
        order = self.make_order()
        bar = compact_bar(self.page(order))
        for marker in ("order-compact-bar__name", "data-compact-status", "order-compact-bar__number",
                       "data-save-chip", "data-compact-recipient", order.number):
            self.assertIn(marker, bar)
        self.assertEqual(bar.count("data-return-to"), 1)


class OrderCompactBackStyleTests(SimpleTestCase):
    def test_mobile_back_is_44px_icon_with_focus_ring(self):
        styles = (Path(settings.BASE_DIR) / "static/css/order-workspace.css").read_text(encoding="utf-8")
        self.assertIn(".order-compact-bar__back:focus-visible { outline: 3px solid var(--focus-ring)", styles)
        # 1100px 以下只留 44px 圖示鍵；600px 以下精簡列改兩行，姓名、狀態、算給誰都不被擠掉。
        narrow = styles.split("@media (max-width: 1100px) {\n", 1)[1].split("\n}", 1)[0]
        self.assertIn(".order-compact-bar__back { justify-content: center; width: 44px; min-height: 44px;", narrow)
        self.assertIn(".order-compact-bar__back-text { display: none; }", narrow)
        mobile = styles.split("@media (max-width: 600px) {\n  .order-compact-bar {", 1)[1].split("\n}", 1)[0]
        self.assertIn("grid-template-columns: 44px minmax(0, 1fr) auto", mobile)
        for kept in (".order-compact-bar__name { grid-area: 1 / 2; }", ".order-compact-bar__recipient { grid-area: 2 / 2;"):
            self.assertIn(kept, mobile)
        reduced = [line for line in styles.splitlines() if "prefers-reduced-motion" in line and "order-compact-bar__back" in line]
        self.assertTrue(reduced)

    def test_return_links_are_wired_by_shared_navigation(self):
        script = (Path(settings.BASE_DIR) / "static/js/ui-navigation.js").read_text(encoding="utf-8")
        self.assertIn('document.querySelectorAll("a[data-return-to]")', script)
