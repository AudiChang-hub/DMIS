"""T-306 訂單總覽區段跳轉列：一行放不下時往下換列，不再在電腦版橫向捲動、把右邊的按鈕藏起來。"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

CSS = Path(settings.BASE_DIR) / "static" / "css" / "order-overview.css"


class OrderOverviewJumpWrapTests(SimpleTestCase):
    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8")

    def base_rule(self, selector):
        """取不在 @media 內（行首無縮排）的規則內容。"""
        match = re.search(rf"^{re.escape(selector)} \{{([^}}]*)\}}", self.css, re.MULTILINE)
        self.assertIsNotNone(match, selector)
        return match.group(1)

    def test_jump_bar_wraps_on_every_width(self):
        rule = self.base_rule(".order-overview__jump")
        self.assertIn("flex-wrap: wrap;", rule)
        # 列與列、按鈕與按鈕之間沿用既有 spacing token。
        self.assertIn("gap: var(--space-2);", rule)

    def test_jump_bar_does_not_hide_buttons_behind_horizontal_scroll(self):
        rule = self.base_rule(".order-overview__jump")
        self.assertNotRegex(rule, r"overflow(-x)?:\s*(auto|scroll|hidden)")
        self.assertNotIn("scrollbar-width: none", rule)
        self.assertNotIn(".order-overview__jump::-webkit-scrollbar", self.css)
