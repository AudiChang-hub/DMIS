"""T-140 第 4～9 點（使用者 2026-11-11）：報表的「圖表操作」選單。
分組加標題、匯出先按再選格式、PNG 下載與複製合併、拿掉複製連結／查看資料口徑／報表設計器入口。
只改圖表選單元件（report-overview.js、report-overview.css），報表設計器本身不動。"""
import re
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]


def read(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


class ReportChartMenuTests(SimpleTestCase):
    def test_menu_groups_have_titles_and_sort_is_labelled(self):
        js = read("static", "js", "report-overview.js")
        for title in ("排序方式", "日期層級", "查看", "匯出"):
            self.assertIn(f"group('{title}')", js)
        self.assertIn("box.setAttribute('aria-labelledby', heading.id)", js)
        self.assertIn("sort.setAttribute('aria-labelledby'", js)

    def test_export_asks_format_after_click(self):
        js = read("static", "js", "report-overview.js")
        self.assertIn("'匯出資料…'", js)
        self.assertNotIn("setAttribute('aria-label','匯出格式')", js)  # 選單裡不再先選格式
        self.assertIn("要匯出哪種格式？", js)
        self.assertIn("a.report-export", js)  # 一般版型報表的「匯出 CSV」也先問格式
        # 沒選格式在原地提示，不觸發全站「目前無法送出」與處理中提示
        self.assertIn("form.noValidate = true; form.dataset.noBusy = '';", js)
        self.assertIn("請先選擇匯出格式。", js)

    def test_image_actions_merged_and_entries_removed(self):
        js = read("static", "js", "report-overview.js")
        self.assertIn("'圖表圖片（PNG）…'", js)
        self.assertIn("'下載 PNG'", js)
        self.assertIn("'複製圖片'", js)
        for removed in ("act('另存為 PNG'", "act('複製圖表圖片'", "複製此圖連結（含篩選）", "act('查看資料口徑'", "在報表設計器探索（admin）"):
            self.assertNotIn(removed, js)

    def test_report_designer_itself_untouched(self):
        self.assertIn("data-report-editor-url", read("templates", "sales", "reporting", "display.html"))

    def test_menu_styles_stay_in_report_overview_css(self):
        css = read("static", "css", "report-overview.css")
        block = re.sub(r"/\*.*?\*/", "", css[css.index("/* ===== T-140"):], flags=re.S)
        selectors = re.findall(r"([^{}]+)\{[^{}]*\}", block)
        self.assertTrue(selectors)
        for selector in selectors:
            for part in selector.split(","):
                if part.strip() and not part.strip().startswith("@"):
                    self.assertTrue(part.strip().startswith(".report-"), part)
        self.assertNotIn("T-140", read("static", "css", "app.css"))
