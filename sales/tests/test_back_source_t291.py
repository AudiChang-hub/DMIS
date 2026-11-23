"""T-291：全站「從哪來回哪去」返回。

跨區連結帶 back_to＝來源頁的本站相對路徑（含篩選與期間）；目的頁返回列回到來源，標籤用白名單名稱。
惡意或不認得的來源一律不採用，照原本階層返回；沒有 back_to 時頁面輸出與原本相同。
"""
import re
from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import resolve, reverse

from sales.back_source import SOURCE_LABELS, resolve_back_source
from sales.tests import test_order_flow as flow
from sales.tests.test_finance_ledger import FinanceLedgerTestBase
from sales.tests.test_order_compact_back_t214 import compact_bar


def back_nav(html):
    match = re.search(r'<nav class="page-context-nav".*?</nav>', html, re.S)
    return match.group(0) if match else ""


def parent_link(html):
    match = re.search(r'<li class="page-breadcrumb-parent"><a class="back-link" href="([^"]*)"[^>]*>.*?<span>([^<]*)</span></a>', back_nav(html), re.S)
    return (match.group(1).replace("&amp;", "&"), match.group(2)) if match else (None, None)


class BackSourceResolveTests(SimpleTestCase):
    def source(self, value, path="/data/inventory/"):
        request = RequestFactory().get(path, {"back_to": value})
        request.resolver_match = resolve(path)
        return resolve_back_source(request)

    def test_allowed_source_keeps_query(self):
        source = self.source("/operations/?period=month")
        self.assertEqual(source["url"], "/operations/?period=month")
        self.assertEqual(source["label"], "營運總表")

    def test_malicious_or_unknown_sources_are_rejected(self):
        for value in (
            "//evil.example/operations/", "https://evil.example/operations/", "http://testserver/operations/",
            "javascript:alert(1)", r"/\evil.example", r"\\evil.example", "/%5Cevil.example", " //evil.example", "operations/",
            "/operations/\n", "/no-such-page/", "/orders/new/", "/" + "a" * 2100,
        ):
            with self.subTest(value=value):
                self.assertIsNone(self.source(value))

    def test_source_equal_to_current_page_is_ignored(self):
        self.assertIsNone(self.source("/data/inventory/?status=active"))

    def test_every_whitelisted_route_exists(self):
        from django.urls import get_resolver
        names = {name for name in get_resolver().reverse_dict.keys() if isinstance(name, str)}
        self.assertEqual(sorted(set(SOURCE_LABELS) - names), [])


class BackSourcePageTests(FinanceLedgerTestBase):
    def setUp(self):
        self.client.force_login(self.admin)

    def test_inventory_from_operations_returns_to_operations_with_period(self):
        url = reverse("inventory_list") + "?back_to=" + quote("/operations/?period=quarter", safe="")
        href, label = parent_link(self.client.get(url).content.decode())
        self.assertEqual((href, label), ("/operations/?period=quarter", "營運總表"))

    def test_order_list_from_operations_attention_shows_back_link(self):
        # 全部訂單原本上一層是首頁、不顯示返回列；從營運總表「需要處理」進來就要回得去。
        url = reverse("order_list") + "?attention=dealer&back_to=" + quote("/operations/?period=month", safe="")
        html = self.client.get(url).content.decode()
        self.assertEqual(parent_link(html), ("/operations/?period=month", "營運總表"))
        self.assertIn('aria-label="回到營運總表"', back_nav(html))
        self.assertNotIn("page-breadcrumb-root", back_nav(html))

    def test_malicious_source_falls_back_to_hierarchy(self):
        plain = self.client.get(reverse("inventory_list")).content.decode()
        for value in ("//evil.example/", "https://evil.example/", "javascript:alert(1)", "/no-such-page/"):
            with self.subTest(value=value):
                html = self.client.get(reverse("inventory_list") + "?back_to=" + quote(value, safe="")).content.decode()
                self.assertEqual(back_nav(html), back_nav(plain))
                self.assertNotIn("evil.example", back_nav(html))
                self.assertNotIn("javascript:", back_nav(html))

    def test_without_source_breadcrumbs_are_unchanged(self):
        self.assertEqual(parent_link(self.client.get(reverse("inventory_list")).content.decode()),
                         (reverse("data_maintenance"), "資料維護區"))
        self.assertEqual(back_nav(self.client.get(reverse("order_list")).content.decode()), "")
        recon = back_nav(self.client.get(reverse("reconciliation_list")).content.decode())
        self.assertIn('class="page-breadcrumb-root"', recon)
        self.assertEqual(parent_link(recon), (reverse("operations_report"), "營運總表"))

    def test_source_equal_to_parent_only_swaps_url(self):
        # 從營運總表（帶期間）進統一撥款對帳：上一層本來就是營運總表，保留首頁麵包屑，只把網址換成來源。
        url = reverse("reconciliation_list") + "?back_to=" + quote("/operations/?period=year", safe="")
        nav = back_nav(self.client.get(url).content.decode())
        self.assertIn('class="page-breadcrumb-root"', nav)
        self.assertEqual(parent_link(nav), ("/operations/?period=year", "營運總表"))

    def test_site_navigation_pages_follow_source(self):
        url = reverse("report_center") + "?back_to=" + quote("/operations/", safe="")
        self.assertEqual(parent_link(self.client.get(url).content.decode()), ("/operations/", "營運總表"))

    def test_only_whitelisted_pages_mark_links_as_source(self):
        for name in ("operations_report", "order_list", "inventory_list", "data_maintenance", "dashboard"):
            with self.subTest(name=name):
                self.assertIn('id="main-content" tabindex="-1" data-link-source>',
                              self.client.get(reverse(name)).content.decode())
        self.assertIn('id="main-content" tabindex="-1">',
                      self.client.get(reverse("user_guide")).content.decode())



class OrderCompactBarSourceTests(TestCase):
    """手機上訂單頁頂端是精簡列（麵包屑被取代），精簡列返回鍵也要回到來源。"""
    setUp = flow.OrderFlowTests.setUp
    make_order = flow.OrderFlowTests.make_order

    def links(self, query=""):
        admin = get_user_model().objects.filter(username="admin").first() or get_user_model().objects.create_superuser(
            "admin", password="test-only")
        self.client.force_login(admin)
        page = self.client.get(reverse("order_detail", args=[self.make_order().pk]) + query).content.decode()
        crumb = re.search(r'<a class="back-link" href="([^"]+)" data-return-to aria-label="([^"]+)"', page)
        bar = compact_bar(page)
        back = re.search(r'<a class="order-compact-bar__back" href="([^"]+)" data-return-to aria-label="([^"]+)">'
                         r'.*?__back-text">([^<]+)<', bar)
        return crumb.groups(), back.groups()

    def test_compact_back_follows_source(self):
        crumb, back = self.links("?back_to=" + quote("/operations/?period=last_month", safe=""))
        self.assertEqual(crumb, ("/operations/?period=last_month", "回到營運總表"))
        self.assertEqual(back, ("/operations/?period=last_month", "回到營運總表", "營運總表"))

    def test_compact_back_keeps_filtered_order_list(self):
        crumb, back = self.links("?back_to=" + quote("/orders/?status=active", safe=""))
        self.assertEqual(crumb, ("/orders/?status=active", "回到全部訂單"))
        self.assertEqual(back, ("/orders/?status=active", "回到全部訂單", "全部訂單"))

    def test_compact_back_unchanged_without_or_with_bad_source(self):
        for query in ("", "?back_to=" + quote("//evil.example/", safe="")):
            with self.subTest(query=query):
                crumb, back = self.links(query)
                self.assertEqual(back, (reverse("order_list"), "回到全部訂單", "全部訂單"))
                self.assertEqual(back[:2], crumb)


class VehicleModelWorkspaceSourceTests(FinanceLedgerTestBase):
    """機種工作區：從其他區（例：營運總表→缺貨風險車型）進來，切分頁、換年式後返回仍回到來源。"""
    SOURCE = "/data/inventory/shortage/"

    def setUp(self):
        self.client.force_login(self.admin)

    def page(self, query=""):
        return self.client.get(reverse("vehicle_model_edit", args=[self.model.pk]) + query).content.decode()

    @staticmethod
    def workspace_links(html):
        tabs = re.findall(r'<a class="model-workspace-tab[^"]*" href="([^"]+)"', html)
        years = re.findall(r'<a class="model-nav__year[^"]*" href="([^"]+)"', html)
        return [href.replace("&amp;", "&") for href in tabs + years]

    def test_tabs_and_model_switch_keep_source(self):
        html = self.page("?back_to=" + quote(self.SOURCE, safe=""))
        self.assertEqual(parent_link(html), (self.SOURCE, "缺貨風險車型"))
        links = self.workspace_links(html)
        self.assertGreater(len(links), 2)
        for href in links:
            with self.subTest(href=href):
                self.assertTrue(href.endswith("?back_to=" + quote(self.SOURCE, safe="")), href)
        price_tab = reverse("vehicle_model_price_versions", args=[self.model.pk])
        next_page = next(href for href in links if href.startswith(price_tab + "?"))
        self.assertEqual(parent_link(self.client.get(next_page).content.decode()), (self.SOURCE, "缺貨風險車型"))

    def test_without_or_with_bad_source_workspace_is_unchanged(self):
        plain = self.page()
        self.assertEqual(parent_link(plain), (reverse("vehicle_model_list"), "機種與售價"))
        self.assertTrue(all("back_to" not in href for href in self.workspace_links(plain)))
        for value in ("//evil.example/", "/no-such-page/"):
            with self.subTest(value=value):
                html = self.page("?back_to=" + quote(value, safe=""))
                self.assertEqual(self.workspace_links(html), self.workspace_links(plain))
                self.assertEqual(back_nav(html), back_nav(plain))
