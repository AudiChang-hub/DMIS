"""T-297：右下角懸浮鈕（回頂端、回來源頁）。

有來源時「← 來源名稱」與左上角返回列同一組網址與名稱（照抄返回列實際顯示的結果，不另判斷）；
惡意或不認得的 back_to 不顯示來源鈕；沒有來源只有「↑」；訂單頁精簡列已有返回鍵，只放「↑」。
"""
import re
from pathlib import Path
from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from sales.tests import test_order_flow as flow
from sales.tests.test_back_source_t291 import parent_link
from sales.tests.test_finance_ledger import FinanceLedgerTestBase


def dock(html):
    match = re.search(r'<nav class="page-dock" aria-label="快速移動" data-page-dock>(.*?)</nav>', html, re.S)
    return match.group(1) if match else None


def dock_back(html):
    match = re.search(r'<a class="page-dock__button page-dock__back" href="([^"]*)" data-return-to aria-label="([^"]*)">'
                      r'.*?<span class="page-dock__label">([^<]*)</span></a>', dock(html) or "", re.S)
    return (match.group(1).replace("&amp;", "&"), match.group(2), match.group(3)) if match else None


def crumb_aria(html):
    match = re.search(r'<li class="page-breadcrumb-parent"><a class="back-link" href="[^"]*" data-return-to aria-label="([^"]*)"', html)
    return match.group(1) if match else None


def has_top(html):
    return 'data-page-dock-top' in (dock(html) or "") and 'aria-label="回到頁面頂端"' in (dock(html) or "")


class PageDockPageTests(FinanceLedgerTestBase):
    def setUp(self):
        self.client.force_login(self.admin)

    def get(self, name, back_to=None, query=""):
        url = reverse(name) + query
        if back_to is not None:
            url += ("&" if "?" in url else "?") + "back_to=" + quote(back_to, safe="")
        return self.client.get(url).content.decode()

    def assert_same_as_back_row(self, html):
        href, label = parent_link(html)
        self.assertIsNotNone(href)
        self.assertEqual(dock_back(html), (href, crumb_aria(html), label))

    def test_source_matches_back_row(self):
        cases = [
            ("inventory_list", "/operations/?period=quarter", ""),           # 來源不是上一層：「← 營運總表」
            ("order_list", "/operations/?period=month", "?attention=dealer"),  # 全部訂單原本沒有返回列
            ("reconciliation_list", "/operations/?period=year", ""),         # 來源就是上一層：只換網址
            ("report_center", "/operations/", ""),                           # site_navigation 頁
        ]
        for name, source, query in cases:
            with self.subTest(name=name):
                html = self.get(name, source, query)
                self.assertTrue(has_top(html))
                self.assert_same_as_back_row(html)
                self.assertEqual(dock_back(html)[0], source)

    def test_label_follows_back_row_when_source_is_parent(self):
        # 來源就是上一層時返回列顯示的是該頁自己的上一層名稱；懸浮鈕照抄，不用白名單名稱另寫一份。
        html = self.get("reconciliation_list", "/operations/?period=year")
        self.assertEqual(dock_back(html), ("/operations/?period=year", "回到營運總表", "營運總表"))

    def test_malicious_or_unknown_source_shows_only_top(self):
        for value in ("//evil.example/", "https://evil.example/operations/", "javascript:alert(1)", "/no-such-page/",
                      r"/\evil.example", "/operations/\n"):
            with self.subTest(value=value):
                html = self.get("inventory_list", value)
                self.assertTrue(has_top(html))
                self.assertIsNone(dock_back(html))
                self.assertNotIn("evil.example", dock(html))
                self.assertNotIn("javascript:", dock(html))

    def test_without_source_only_top(self):
        for name in ("inventory_list", "order_list", "operations_report", "dashboard", "report_center"):
            with self.subTest(name=name):
                html = self.get(name)
                self.assertTrue(has_top(html))
                self.assertIsNone(dock_back(html))
                self.assertNotIn("<a", dock(html))

    def test_hidden_back_row_shows_only_top(self):
        # 返回列沒有顯示「← 來源」（例：來源就是首頁且上一層也是首頁，返回列整列不出現）時，懸浮鈕也不放。
        html = self.get("order_list", "/")
        self.assertIsNone(parent_link(html)[0])
        self.assertIsNone(dock_back(html))
        self.assertTrue(has_top(html))

    def test_dock_is_rendered_once_after_main(self):
        html = self.get("inventory_list", "/operations/")
        self.assertEqual(html.count("data-page-dock>"), 1)
        self.assertEqual(html.count("data-page-dock-spacer"), 1)
        self.assertLess(html.index("</main>"), html.index("data-page-dock>"))
        self.assertIn("js/page-dock.js", html)


class PageDockOrderDetailTests(TestCase):
    """訂單頁精簡列已有返回鍵（T-214），懸浮鈕只放「↑」，帶來源也一樣。"""
    setUp = flow.OrderFlowTests.setUp
    make_order = flow.OrderFlowTests.make_order

    def test_order_detail_only_top(self):
        admin = get_user_model().objects.filter(username="admin").first() or get_user_model().objects.create_superuser(
            "admin", password="test-only")
        self.client.force_login(admin)
        url = reverse("order_detail", args=[self.make_order().pk])
        for query in ("", "?back_to=" + quote("/operations/?period=month", safe="")):
            with self.subTest(query=query):
                html = self.client.get(url + query).content.decode()
                self.assertTrue(has_top(html))
                self.assertIsNone(dock_back(html))
                self.assertNotIn("<a", dock(html))


class PageDockStyleTests(SimpleTestCase):
    css = Path("static/css/app.css").read_text(encoding="utf-8").replace("\r\n", "\n")

    def block(self, selector):
        match = re.search(r"\n" + re.escape(selector) + r" \{([^}]*)\}", self.css)
        self.assertIsNotNone(match, selector)
        return match.group(1)

    def test_layer_safe_area_touch_target_and_print(self):
        dock_rule = self.block(".page-dock")
        self.assertIn("z-index: 35;", dock_rule)  # 黏住的儲存列（20）之上、側邊目錄（39–41）、手機主選單（50）、提示與彈窗之下
        self.assertIn("env(safe-area-inset-bottom)", dock_rule)
        button = self.block(".page-dock__button")
        self.assertIn("min-width: 44px; min-height: 44px;", button)
        self.assertIn(".page-dock__button:focus-visible { outline: 3px solid var(--focus-ring);", self.css)
        self.assertRegex(self.css, r"@media print \{\n  \.page-dock, \.page-dock-spacer \{ display: none !important; \}")
        phone = re.search(r"@media \(max-width: 860px\) \{\n  \.page-dock \{([^}]*)\}", self.css)
        self.assertIn("var(--mobile-nav-height, 72px)", phone.group(1))
        self.assertIn("env(safe-area-inset-bottom)", phone.group(1))
        self.assertRegex(self.css, r"@media \(prefers-reduced-motion: reduce\) \{\n  \.page-dock, \.page-dock\.is-shown")


class PageDockCopiesBackRowTests(SimpleTestCase):
    """來源就是上一層、但返回列用頁面自己的名稱（與白名單名稱不同）時，懸浮鈕照抄返回列的名稱。"""

    def test_parent_label_differs_from_whitelist(self):
        from django.template import Context, Template
        from django.test import RequestFactory
        from django.urls import resolve

        source_list = reverse("sales_source_list")
        request = RequestFactory().get("/data/inventory/", {"back_to": source_list + "?kind=dealer"})
        request.resolver_match = resolve("/data/inventory/")
        html = Template(
            '{% load back_source_tags %}{% include "sales/_page_back.html" with fallback_url=list_url label="車行、平台與傭金" %}'
            "{% page_dock %}"
        ).render(Context({"request": request, "list_url": source_list}))
        self.assertEqual(parent_link(html), (source_list + "?kind=dealer", "車行、平台與傭金"))
        self.assertEqual(dock_back(html), (source_list + "?kind=dealer", "回到車行、平台與傭金", "車行、平台與傭金"))
