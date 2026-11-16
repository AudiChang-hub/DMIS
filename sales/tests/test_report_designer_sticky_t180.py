"""T-180 報表設計器右側「正在設定」面板：捲動時固定在頁首下方，內容過長在面板內捲動。"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

STATIC = Path(settings.BASE_DIR) / "static"


def rule(css, selector):
    """回傳 selector 這條規則（完全相同的選擇器）的宣告內容。"""
    match = re.search(re.escape(selector) + r"\{([^}]*)\}", css)
    assert match, f"找不到 {selector}"
    return match.group(1)


class ReportDesignerStickyPanelT180Tests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.css = (STATIC / "css/report-designer.css").read_text(encoding="utf-8")
        cls.js = (STATIC / "js/report-designer.js").read_text(encoding="utf-8")

    def test_panel_sticks_below_header_and_scrolls_inside(self):
        panel = rule(self.css, "[data-report-editor] .report-property-panel")
        self.assertIn("position:sticky", panel)
        self.assertIn("top:var(--designer-sticky-top)", panel)
        self.assertIn("align-self:start", panel)
        self.assertIn("max-height:var(--designer-panel-fit, var(--designer-panel-max))", panel)
        self.assertIn("overflow:auto", panel)
        bench = rule(self.css, "[data-report-editor] .report-design-workbench")
        self.assertIn("--designer-sticky-top:calc(var(--app-header-height, 73px) + var(--space-3))", bench)
        # overflow:hidden 會建立捲動容器讓 sticky 失效；clip 只裁切圓角。
        self.assertIn("overflow:clip", bench)
        # 畫布區至少與面板一樣高：面板縮放不改變工作台高度，也避免反覆重算。
        self.assertIn("min-height:var(--designer-panel-max)", rule(self.css, "[data-report-editor] .report-canvas-area"))

    def test_stacked_and_fullscreen_layouts_stay_static(self):
        narrow = self.css[self.css.index("@media(max-width:850px)"):]
        self.assertIn("[data-report-editor] .report-property-panel{position:static;max-height:none", narrow)
        self.assertIn("[data-report-editor] .report-canvas-area{min-height:0;border-right:0}", narrow)
        self.assertIn(".designer-focused [data-report-editor] .report-property-panel{position:static;max-height:none", self.css)

    def test_script_fits_panel_between_header_and_savebar(self):
        self.assertIn("--designer-panel-fit", self.js)
        self.assertIn("savebar.getBoundingClientRect().top - gap", self.js)
        self.assertIn("bench.getBoundingClientRect().bottom", self.js)
        self.assertIn("matchMedia('(max-width:850px)')", self.js)
        self.assertIn("window.addEventListener('scroll', queueFitPanel, {passive: true})", self.js)
