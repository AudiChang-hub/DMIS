"""T-141：報表中心可點文字加底線；點選後只反白、不畫框，鍵盤焦點仍看得到。"""
import re
from pathlib import Path

from django.test import TestCase
from django.urls import reverse

from sales.reporting.engine import validate_config
from sales.reporting.source_templates import SOURCE_TEMPLATES
from sales.tests import test_reporting as fixtures

CSS_DIR = Path(__file__).resolve().parents[2] / "static" / "css"


def css_rules(name):
    """回傳 (selector, declarations) 清單；@media 內的規則一併攤平。"""
    text = re.sub(r"/\*.*?\*/", "", (CSS_DIR / name).read_text(encoding="utf-8"), flags=re.S)
    rules = []
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
        selector = re.sub(r"^\s*@media[^{]*\{", "", selector).strip()
        rules.append((" ".join(selector.split()), body.strip()))
    return rules


def selectors(found):
    """只在最外層逗號切開，:is(a,b) 這類括號內的逗號保留。"""
    parts, depth, current = [], 0, ""
    for char in found:
        depth += {"(": 1, ")": -1}.get(char, 0)
        if char == "," and not depth:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    return parts + [current.strip()]


def declarations(rules, selector):
    return [body for found, body in rules if selector in selectors(found)]


class ReportLinkAffordanceCssTests(TestCase):
    def setUp(self):
        self.rules = css_rules("reporting.css")
        self.overview_rules = css_rules("report-overview.css")

    def test_clickable_report_text_is_underlined_only_inside_report_workspace(self):
        selector = ".report-workspace :is(.report-results,.report-score,.report-stack-data) a:not(.button)"
        bodies = declarations(self.rules, selector)
        self.assertTrue(any("text-decoration-line:underline" in body for body in bodies), bodies)
        self.assertTrue(any("text-decoration-line:underline" in body for body in declarations(self.rules, ".report-workspace a.report-export")))
        # 底線規則都限定在報表中心範圍內，不改全站連結。
        for found, body in self.rules:
            if "underline" in body:
                for part in selectors(found):
                    self.assertTrue(part.startswith(".report-workspace"), found)
        app_css = (CSS_DIR / "app.css").read_text(encoding="utf-8")
        self.assertIn("a { color: inherit; text-decoration: none; }", app_css)

    def test_selected_items_are_highlighted_without_a_frame(self):
        # 根因：閱讀器的選取樣式用 outline 畫框；多欄彙總表的選取類別直接加在連結上，框就圍住文字。
        self.assertIn("outline:none", declarations(self.rules, ".report-reader-shell .report-workspace .report-row-selected")[0])
        highlight = declarations(self.rules, ".report-workspace tr:has(>th>a.report-row-selected)")[0]
        self.assertIn("background:", highlight)
        self.assertIn("box-shadow:none", highlight)
        self.assertIn("background:none", declarations(self.rules, ".report-workspace :is(th,td)>a.report-row-selected")[0])
        for body in declarations(self.rules, ".report-reader-shell .report-sales-overview .report-point-selected"):
            self.assertNotIn("outline", body)
        month = declarations(self.overview_rules, ".report-sales-overview .report-month-target.report-point-selected")[0]
        self.assertIn("fill:", month)
        self.assertNotIn("stroke", month)

    def test_keyboard_focus_ring_is_kept(self):
        focus = declarations(self.rules, ".report-workspace :is(input,select,textarea,button,a):focus-visible")
        self.assertTrue(any("outline:3px solid var(--focus-ring)" in body for body in focus), focus)
        self.assertTrue(declarations(self.rules, ".report-chart [tabindex]:focus-visible"))
        for found, body in self.rules + self.overview_rules:
            if ":focus" in found and ":focus-visible" not in found and ":focus-within" not in found:
                self.fail(f"報表不可在滑鼠點擊的 :focus 畫框：{found}")


class ReportLinkAffordanceMarkupTests(TestCase):
    login = fixtures.ReportingTests.login

    @classmethod
    def setUpTestData(cls):
        fixtures.ReportingTests.setUpTestData.__func__(cls)

    def test_count_overview_drill_links_sit_in_row_headers_covered_by_the_styles(self):
        config = validate_config(SOURCE_TEMPLATES["gasoline-count"]())
        self.report.published = config
        self.report.save()
        self.login()
        response = self.client.get(reverse("report_display", args=[self.report.pk]))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('class="report-results report-summary-table"', html)
        # 反白整列靠 tr:has(>th>a.report-row-selected)，連結必須是列標題的直接子元素。
        self.assertRegex(html, r'<th scope="row"><a data-report-drill href=')
        self.assertIn("data-report-open-detail", html)
