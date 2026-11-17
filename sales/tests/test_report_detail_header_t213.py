"""T-213：報表中心「目前篩選的來源訂單」面板，往下捲動後「關閉明細」不能跟著捲走。

根因：面板（.report-inline-detail）本身是捲動容器（overflow:auto；讀者頁再設 position:fixed 固定高度），
標題列（.report-card-toolbar：標題＋關閉明細）只是一般子元素，所以清單捲動時一起捲走。
修正：標題列在面板內 sticky 置頂，背景蓋住底下捲動的清單。
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
CSS = re.sub(r"/\*.*?\*/", "", (ROOT / "static" / "css" / "reporting.css").read_text(encoding="utf-8"), flags=re.S)
DISPLAY = (ROOT / "templates" / "sales" / "reporting" / "display.html").read_text(encoding="utf-8")


def rules(selector):
    """回傳某個選擇器（完全相符）的所有宣告，依出現順序合併。"""
    found = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS):
        if selector in [part.strip() for part in selectors.split(",")]:
            for name, value in re.findall(r"([\w-]+)\s*:\s*([^;]+)", body):
                found[name] = value.strip()
    return found


class DetailPanelHeaderTests(SimpleTestCase):
    def test_panel_is_the_scroll_container_and_header_is_its_direct_child(self):
        self.assertEqual(rules(".report-inline-detail").get("overflow"), "auto")
        self.assertEqual(rules(".report-reader-shell .report-inline-detail").get("position"), "fixed")
        panel = re.search(r'<section class="report-panel report-inline-detail"[^>]*>(.*?)</section>', DISPLAY, re.S).group(1)
        self.assertTrue(panel.startswith('<header class="report-card-toolbar">'))
        self.assertIn("data-detail-clear", panel.split("</header>", 1)[0])

    def test_header_with_close_button_stays_pinned_while_list_scrolls(self):
        header = rules(".report-inline-detail > .report-card-toolbar")
        self.assertEqual(header.get("position"), "sticky")
        self.assertEqual(header.get("top"), "calc(-1 * var(--card-pad))")  # sticky 扣掉面板內距，負內距才貼齊上緣
        self.assertEqual(header.get("background"), "var(--surface)")
        self.assertIn("z-index", header)
        # 延伸到面板內距，捲動中的清單不會從標題列兩側或上方露出。
        self.assertEqual(header.get("margin-top"), "calc(-1 * var(--card-pad))")
        self.assertEqual(header.get("padding-top"), "var(--card-pad)")
