"""T-300：全站紅（優先）、黃（注意）兩級要一眼分得出來，色弱與讀螢幕軟體也分得出來。

顏色（方案甲）：改共用 token，--red 亮 #c8102e／暗 #ff5468、--amber-strong 亮 #c47c00／暗 #f6c12f；
對卡片底都 ≥ 3:1（WCAG 1.4.11）；新琥珀不能當文字，原本拿 --amber-strong 當文字的改用 --amber-ink。
不靠顏色的提示（方案 A）：優先＝實心點加外圈、注意＝空心圈；庫存可銷天數長條的注意那級加斜紋。
讀螢幕軟體唸「（優先）」／「（注意）」。
"""
import copy
import re
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import Store
from sales.services import operations_cockpit

CSS_DIR = Path(settings.BASE_DIR) / "static" / "css"


def _css(name):
    return (CSS_DIR / name).read_text(encoding="utf-8")


class AttentionSeverityMarkupTests(TestCase):
    def setUp(self):
        cache.clear()
        Store.objects.create(name="總店", code="MAIN")
        self.client.force_login(get_user_model().objects.create_superuser("admin", password="Local-t300-sev-518!"))
        data = copy.deepcopy(operations_cockpit.build("month", timezone.localdate()))
        # 紅：庫齡 90 天以上；黃：已收款待確認、缺貨風險。
        data["money"].update({"unconfirmed": 2})
        data["stock"].update({"aged": 1, "oldest": 120, "shortage": ["測試車型"]})
        with patch.object(operations_cockpit, "load", return_value=data):
            response = self.client.get(reverse("operations_report"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        start = html.index('aria-labelledby="ops-attention-title"')
        self.html = html[start:html.index("</section>", start)]

    def item(self, key):
        return re.search(rf'<li class="([^"]*)" data-attention-key="{key}">(.*?)</li>', self.html, re.S).groups()

    def test_red_and_amber_differ_in_class_and_screen_reader_text(self):
        red_class, red_body = self.item("aged")
        amber_class, amber_body = self.item("unconfirmed")
        self.assertIn("ops-todo__item--red", red_class.split())
        self.assertIn("ops-todo__item--amber", amber_class.split())
        self.assertNotEqual(red_class, amber_class)
        self.assertIn('<span class="ops-visually-hidden">（優先）</span>', red_body)
        self.assertNotIn("（注意）", red_body)
        self.assertIn('<span class="ops-visually-hidden">（注意）</span>', amber_body)
        self.assertNotIn("（優先）", amber_body)
        # 圓點本身不給讀螢幕軟體讀（等級由上面的文字表達）。
        self.assertIn('<span class="ops-dot" aria-hidden="true"></span>', red_body)

    def test_legend_shows_the_red_marker(self):
        self.assertIn('<small><span class="ops-dot ops-dot--red" aria-hidden="true"></span>紅色優先，同色依金額與件數排序</small>',
                      self.html)


class OrderRowSeverityMarkupTests(TestCase):
    """訂單清單狀態圓點：紅色那級（取消待退款、已交車／待領牌）讀螢幕唸「（優先）」，其他狀態不唸等級。"""

    def render(self, status):
        order = type("Order", (), {"status": status, "pk": 1, "owner_name": "王小明", "number": "S1"})()
        return render_to_string("sales/_order_row.html", {"order": order})

    def dot(self, html):
        return re.search(r'<span class="status-dot status-[a-z_]+">(.*?)</span>\s*<div class="order-main">', html, re.S).group(1)

    def test_red_statuses_announce_priority(self):
        for status in ("cancel_refund_pending", "delivered_docs_pending"):
            with self.subTest(status=status):
                self.assertEqual(self.dot(self.render(status)), '<span class="visually-hidden">（優先）</span>')

    def test_other_statuses_have_no_level_text(self):
        for status in ("allocation_pending", "completed"):
            with self.subTest(status=status):
                self.assertEqual(self.dot(self.render(status)), "")


def _luminance(hex_color):
    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(a, b):
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class SharedTokenTests(SimpleTestCase):
    """方案甲：改 app.css 共用 token，亮、夜藍、跟隨系統（暗）三組。"""

    def setUp(self):
        self.css = _css("app.css")

    def block(self, opener):
        start = self.css.index(opener)
        depth, i = 0, self.css.index("{", start)
        for j in range(i, len(self.css)):
            depth += {"{": 1, "}": -1}.get(self.css[j], 0)
            if depth == 0:
                return self.css[i:j]
        raise AssertionError(opener)

    def tokens(self, block):
        return dict(re.findall(r"(?m)^\s*--([a-z-]+):\s*(#[0-9a-f]{6});", block))

    def themes(self):
        system = self.block("@media (prefers-color-scheme: dark) {")
        return {
            "light": self.tokens(self.block(":root {")),
            "night-blue": self.tokens(self.block('html[data-theme="night-blue"] {')),
            "system-dark": self.tokens(system[system.index('html[data-theme="system"]'):]),
        }

    def test_token_values(self):
        themes = self.themes()
        self.assertEqual((themes["light"]["red"], themes["light"]["amber-strong"]), ("#c8102e", "#c47c00"))
        for name in ("night-blue", "system-dark"):
            self.assertEqual((themes[name]["red"], themes[name]["amber-strong"]), ("#ff5468", "#f6c12f"), name)

    def test_markers_meet_non_text_contrast_and_separate_in_lightness(self):
        for name, tokens in self.themes().items():
            surface = tokens["surface"]
            for token in ("red", "amber-strong"):
                self.assertGreaterEqual(_contrast(tokens[token], surface), 3, f"{name} --{token} on {surface}")
            # 兩級明度要拉開（舊色只有 1.2），色弱看明度也分得出來。
            self.assertGreaterEqual(_contrast(tokens["red"], tokens["amber-strong"]), 1.7, name)

    def test_red_still_works_as_text(self):
        for name, tokens in self.themes().items():
            for background in ("surface", "red-soft"):
                self.assertGreaterEqual(_contrast(tokens["red"], tokens[background]), 4.5, f"{name} --red on --{background}")

    def test_warning_callout_icon_contrast(self):
        """亮色警告框圖示：白色「!」放在 --amber-ink 圓底上 ≥4.5，圓底對 amber-soft ≥3；暗色維持深色字放在 --amber-strong 上。"""
        self.assertIn(".callout--warning .callout__icon { background: var(--amber-ink); }", self.css)
        self.assertIn('html[data-theme="night-blue"] .callout--warning .callout__icon { background: var(--callout-accent); }', self.css)
        self.assertIn('html[data-theme="system"] .callout--warning .callout__icon { background: var(--callout-accent); }', self.css)
        themes = self.themes()
        light = themes["light"]
        self.assertGreaterEqual(_contrast(light["on-status"], light["amber-ink"]), 4.5)
        self.assertGreaterEqual(_contrast(light["amber-ink"], light["amber-soft"]), 3)
        for name in ("night-blue", "system-dark"):
            dark = themes[name]
            self.assertGreaterEqual(_contrast(dark["on-status"], dark["amber-strong"]), 4.5, name)
            self.assertGreaterEqual(_contrast(dark["amber-strong"], dark["amber-soft"]), 3, name)

    def test_amber_strong_is_no_longer_used_as_text(self):
        for path in sorted(CSS_DIR.glob("*.css")):
            with self.subTest(css=path.name):
                self.assertNotRegex(path.read_text(encoding="utf-8"), r"(?<![-\w])color:\s*var\(--amber-strong\)")


class SeverityShapeTests(SimpleTestCase):
    """方案 A：不靠顏色的形狀提示。"""

    def rule(self, css, selector):
        return re.search(r"(?m)^" + re.escape(selector) + r" \{(.*?)\}", css, re.S).group(1)

    def test_attention_dots_differ_in_shape(self):
        css = _css("operations.css")
        amber = self.rule(css, ".ops-dot")
        self.assertIn("background: transparent", amber)
        self.assertIn("border: 2px solid var(--amber-strong)", amber)
        red = self.rule(css, ".ops-todo__item--red .ops-dot,\n.ops-dot--red")
        self.assertIn("background: var(--red)", red)
        self.assertIn("outline: 2px solid var(--red)", red)
        self.assertNotIn("--ops-sev-", css)

    def test_order_list_dots_differ_in_shape(self):
        css = _css("app.css")
        for status in ("contract_pending", "intake_pending"):
            amber = self.rule(css, f".status-dot.status-{status}")
            self.assertIn("background: transparent", amber)
            self.assertIn("border: 2px solid var(--amber-strong)", amber)
        red = self.rule(css, ".status-dot.status-cancel_refund_pending, .status-dot.status-delivered_docs_pending")
        self.assertIn("background: var(--red)", red)
        self.assertIn("outline: 2px solid var(--red)", red)

    def test_slow_cover_bar_is_striped_and_short_is_solid(self):
        css = _css("operations.css")
        self.assertIn("repeating-linear-gradient(135deg, var(--amber-strong)", self.rule(css, ".ops-cover__bar.is-slow"))
        self.assertIn("background: var(--red)", self.rule(css, ".ops-cover__bar.is-short"))
