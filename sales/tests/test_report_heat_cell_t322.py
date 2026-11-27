"""T-322 車行／平台頁的熱度格：點格子從側邊看那一格的訂單。

片段由原本的 report_detail 提供（同一個 group，加 inline=1&view=cell），所以這裡核對：
筆數等於格子上的數字、月份與車行（平台）的條件正確、權限照原本的下鑽、其他版型與一般明細不受影響。
"""
import re
from datetime import date
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import SalesOrder, SalesSource
from sales.reporting.engine import validate_config
from sales.reporting.source_templates import SOURCE_TEMPLATES
from sales.reporting.views import publication_key
from sales.tests import test_reporting as fixtures

ROOT = Path(settings.BASE_DIR)


class HeatCellBase(TestCase):
    template = "gasoline-dealer"

    @classmethod
    def setUpTestData(cls):
        fixtures.ReportingTests.setUpTestData.__func__(cls)
        # 三張油車車行單（甲 1、乙 2，都在 2026/09）各取不同車主名，並把乙的一張移到 2026/08。
        orders = list(SalesOrder.objects.order_by("pk"))
        for order, name in zip(orders, ("甲九月", "乙九月", "乙八月")):
            order.owner_name = name
            if name == "乙八月":
                order.registration_date = date(2026, 8, 20)
            order.save(update_fields=["owner_name", "registration_date"])

    def setUp(self):
        self.report.published = validate_config(SOURCE_TEMPLATES[self.template]())
        self.report.save()
        self.client.force_login(self.admin)

    def segments(self):
        """閱讀頁那張熱度格圖卡的每一段：(主分類, 細分, 筆數, 下鑽 group)。"""
        response = self.client.get(reverse("report_display", args=[self.report.pk]))
        self.assertEqual(response.status_code, 200)
        result = response.context["results"][0]
        return [(row["label"], segment["label"], segment["count"], segment["key"]) for row in result["rows"] for segment in row["segments"]]

    def cell(self, group, **extra):
        return self.client.get(reverse("report_detail", args=[self.report.pk, 0]),
                               {"group": group, "inline": "1", "view": "cell", "revision": publication_key(self.report), **extra})

    @staticmethod
    def count(html):
        return int(re.search(r'data-cell-count="(\d+)"', html).group(1))

    @staticmethod
    def owners(html):
        return re.findall(r'<span class="report-cell-orders__who"><b>([^<]+)</b>', html)


class DealerHeatCellTests(HeatCellBase):
    def test_every_cell_lists_exactly_the_orders_it_counts(self):
        segments = self.segments()
        self.assertEqual({(dealer, month): count for dealer, month, count, _key in segments},
                         {("甲車行", "2026/09"): 1, ("乙車行", "2026/09"): 1, ("乙車行", "2026/08"): 1})
        expected = {("甲車行", "2026/09"): ["甲九月"], ("乙車行", "2026/09"): ["乙九月"], ("乙車行", "2026/08"): ["乙八月"]}
        for dealer, month, count, key in segments:
            with self.subTest(dealer=dealer, month=month):
                self.assertTrue(key.startswith("c:"))
                response = self.cell(key)
                self.assertEqual(response.status_code, 200)
                html = response.content.decode()
                self.assertEqual(self.count(html), count)          # 標題的張數＝格子上的數字
                self.assertEqual(self.owners(html), expected[(dealer, month)])  # 車行與月份都對
                self.assertEqual(html.count('class="report-cell-orders__item"'), count)

    def test_fragment_is_compact_and_links_to_each_order(self):
        key = next(key for dealer, month, _count, key in self.segments() if (dealer, month) == ("甲車行", "2026/09"))
        html = self.cell(key).content.decode()
        order = SalesOrder.objects.get(owner_name="甲九月")
        self.assertIn(f'href="{reverse("order_detail", args=[order.pk])}"', html)
        self.assertIn("2026/09/01", html)       # 領牌日期
        self.assertIn("報表測試車 · 白", html)   # 車型 · 車色
        self.assertIn("data-cell-orders", html)
        self.assertNotIn("<html", html)          # 只回片段，不是整頁
        self.assertNotIn("<table", html)
        for secret in ("83739807", "0912345678", "測試地址"):  # 不帶證號、電話、地址
            self.assertNotIn(secret, html)

    def test_cell_follows_page_filters(self):
        key = next(key for dealer, month, _count, key in self.segments() if (dealer, month) == ("乙車行", "2026/09"))
        self.assertEqual(self.count(self.cell(key, months="2026-09").content.decode()), 1)
        self.assertEqual(self.count(self.cell(key, months="2026-08").content.decode()), 0)  # 篩掉那個月就沒有這一格
        self.assertIn("report-cell-orders__empty", self.cell(key, months="2026-08").content.decode())

    def test_more_than_fifty_orders_point_to_the_full_list(self):
        template = SalesOrder.objects.get(owner_name="甲九月")
        for index in range(51):
            template.pk = None
            template.number = ""
            template.owner_name = f"甲加開{index:02d}"
            template.save()
        key = next(key for dealer, month, _count, key in self.segments() if (dealer, month) == ("甲車行", "2026/09"))
        html = self.cell(key).content.decode()
        self.assertEqual(self.count(html), 52)
        self.assertEqual(html.count('class="report-cell-orders__item"'), 50)
        more = re.search(r'report-cell-orders__more">[^<]*<a href="([^"]+)"', html).group(1)
        self.assertIn("group=c%3A", more)
        self.assertNotIn("inline=", more)
        self.assertNotIn("view=", more)

    def test_plain_detail_and_other_layouts_are_unchanged(self):
        key = self.segments()[0][3]
        url = reverse("report_detail", args=[self.report.pk, 0])
        base = {"group": key, "inline": "1", "revision": publication_key(self.report)}
        plain = self.client.get(url, base).content.decode()
        self.assertIn("data-detail-content", plain)       # 沒有 view=cell：原本的明細面板
        self.assertNotIn("data-cell-orders", plain)
        for other in ("gasoline", "gasoline-count"):       # 不是熱度格版型：view=cell 沒有作用
            self.report.published = validate_config(SOURCE_TEMPLATES[other]())
            self.report.save()
            html = self.client.get(url, {"group": "__all__", "inline": "1", "view": "cell", "revision": publication_key(self.report)}).content.decode()
            self.assertNotIn("data-cell-orders", html)

    def test_permission_and_stale_revision_follow_existing_drill(self):
        key = self.segments()[0][3]
        self.assertContains(self.cell(key, revision="old"), "報表設計已更新", status_code=409)
        self.assertEqual(self.cell("c:not-json").status_code, 400)
        config = dict(self.report.published)
        config["audience"] = "admin"
        self.report.published = config
        self.report.save()
        self.client.force_login(self.user)                 # 看不到這份報表的人拿不到片段
        self.assertEqual(self.cell(key).status_code, 404)
        self.client.logout()
        self.assertEqual(self.cell(key).status_code, 302)  # 未登入導去登入頁


class PlatformHeatCellTests(HeatCellBase):
    template = "gasoline-platform"

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.shop = SalesSource.objects.create(name="合成平台", source_type="platform")
        for name, month in (("平台九月甲", 9), ("平台九月乙", 9), ("平台十月", 10)):
            SalesOrder.objects.create(
                source_type="platform", source=cls.shop, order_date=date(2026, month, 2), registration_date=date(2026, month, 5),
                registration_completed_at=timezone.now(), owner_type="local", owner_name=name, owner_id_number="A123456789",
                vehicle_model=cls.model, color=cls.color, vehicle_price=10000, actual_balance=10000, calculated_balance=10000,
                payment_type="cash", status="completed")

    def test_month_rows_with_platform_series(self):
        segments = self.segments()   # 平台頁：每列是月份、細分是平台
        self.assertEqual({(month, platform): count for month, platform, count, _key in segments},
                         {("2026/09", "合成平台"): 2, ("2026/10", "合成平台"): 1})
        expected = {"2026/09": ["平台九月乙", "平台九月甲"], "2026/10": ["平台十月"]}
        for month, _platform, count, key in segments:
            with self.subTest(month=month):
                html = self.cell(key).content.decode()
                self.assertEqual(self.count(html), count)
                self.assertEqual(sorted(self.owners(html)), sorted(expected[month]))


class HeatCellPageTests(HeatCellBase):
    def test_segments_carry_the_drill_link_cells_reuse(self):
        html = self.client.get(reverse("report_display", args=[self.report.pk])).content.decode()
        # 格子的網址取自堆疊圖每一段原本的下鑽連結；沒有另開路徑。
        self.assertRegex(html, r'data-stack-segment[^>]*>\s*<a data-report-drill href="/reports/\d+/charts/0/orders/\?[^"]*group=c%3A')
        self.assertIn("js/report-heat.js", html)
        self.assertIn("點格子裡的數字，直接看那個月的訂單，不用換頁。", html)


class HeatCellAssetsTests(SimpleTestCase):
    def test_cells_are_buttons_and_drawer_is_scoped(self):
        heat = (ROOT / "static/js/report-heat.js").read_text(encoding="utf-8")
        self.assertIn("make('button', 'report-heat__open', text)", heat)
        self.assertIn("url.searchParams.set('inline', '1'); url.searchParams.set('view', 'cell');", heat)
        self.assertIn("const href = value > 0 ? (entity.links?.[month] || '') : '';", heat)  # 空白格、沒有連結的格子不是按鈕
        css = (ROOT / "static/css/report-overview.css").read_text(encoding="utf-8")
        self.assertIn(".report-cell-drawer {", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        drawer = css[css.index("/* T-322"):css.index("/* T-311 台數統計")]
        self.assertNotRegex(drawer, r"(?:padding|margin|gap)[a-z-]*:[^;]*\b(?:[3-9]|[1-9]\d+)px")  # 間距用 --space-* token
        from sales.urls import urlpatterns
        report_routes = sorted(pattern.name for pattern in urlpatterns if "/charts/" in str(pattern.pattern))
        self.assertEqual(report_routes, ["report_detail", "report_export"])  # 沒有新增圖卡網址，片段走原本的 report_detail
