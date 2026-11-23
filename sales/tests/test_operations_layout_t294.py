"""T-294（使用者 2026-11-23 同意 PM 的整頁編排建議）：營運總表只改區塊位置與寬度。

- 順序：現在好不好 → 需要處理 → 訂單流程 → 錢 → 貨＋油電領牌 → 結構變化｜車型貢獻 → 台數獎金｜原廠獎勵 → 資料可信度；
  側邊目錄依頁面上的 data-side-nav-section 順序產生，跟著一起換。
- 需要處理、訂單流程、錢整列全寬（不放在 .ops-row 裡）；貨與油電領牌同一列（約 2：1）；其餘兩兩並排；不再用 .ops-stack。
- 需要處理沒有事時收成一行。
"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from sales.models import IncentiveCampaign, PaymentRecord, SalesOrder, Store, VehicleInventory
from sales.reporting.payout_models import DealerPayoutEntry

ORDER = ["現在好不好", "需要處理", "訂單流程", "錢", "貨", "油電領牌", "結構變化", "車型貢獻",
         "台數獎金進度", "原廠獎勵", "資料可信度"]


class OperationsLayoutTests(TestCase):
    def setUp(self):
        Store.objects.create(name="總店", code="MAIN")
        self.root = get_user_model().objects.create_superuser("admin", password="Local-t294-layout-581!")
        self.client.force_login(self.root)

    def page(self):
        response = self.client.get(reverse("operations_report"))
        self.assertEqual(response.status_code, 200)
        return response, response.content.decode()

    def test_sections_follow_the_question_order(self):
        _response, html = self.page()
        found = re.findall(r'data-side-nav-section="([^"]+)"', html[html.index("data-ops"):])
        self.assertEqual(found, ORDER)

    def test_full_width_blocks_and_pairs(self):
        _response, html = self.page()
        self.assertNotIn("ops-stack", html)
        self.assertNotIn("ops-row--wide", html)
        rows = re.findall(r'<div class="ops-row[^"]*">(.*?)\n  </div>', html, re.S)
        labels = [re.findall(r'data-side-nav-section="([^"]+)"', row) for row in rows]
        self.assertEqual(labels, [["貨", "油電領牌"], ["結構變化", "車型貢獻"], ["台數獎金進度", "原廠獎勵"]])
        self.assertIn('<div class="ops-row ops-row--stock">', html)
        for title in ("ops-attention-title", "ops-flow-title", "ops-money-title"):
            start = html.index(f'aria-labelledby="{title}"')
            self.assertFalse(any(start in range(html.index(row), html.index(row) + len(row)) for row in rows), title)

    def clear_page(self):
        """一定沒有待處理事項的資料：沒有訂單、庫存、收款與車行給付；唯一可能由 migration 帶進來的
        原廠獎勵全部停用。refresh=1 不讀快取。"""
        IncentiveCampaign.objects.update(active=False)
        for model in (SalesOrder, VehicleInventory, PaymentRecord, DealerPayoutEntry):
            self.assertFalse(model.objects.exists(), model.__name__)
        response = self.client.get(reverse("operations_report"), {"refresh": 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["cockpit"]["attention"], [])
        return response, response.content.decode()

    def test_attention_collapses_to_one_line_when_clear(self):
        response, html = self.clear_page()
        self.assertIn('class="ops-card ops-attention is-clear"', html)
        clear = "、".join(response.context["cockpit"]["attention_clear"])
        self.assertIn("已收款待確認", clear)
        # 同一行（同一個 <p>）裡同時有狀態和「目前沒有：…」清單。
        self.assertIn('<p class="ops-attention__none"><span class="ops-attention__ok" aria-hidden="true">✓</span>'
                      f'<strong>目前沒有需要處理的事</strong><small>目前沒有：{clear}</small></p>', html)
        self.assertNotIn("收款、撥款、庫存與流程都在正常範圍內。", html)
        self.assertNotIn('class="ops-clear"', html)
        self.assertNotIn("紅色優先，同色依金額與件數排序", html)

    def test_reconciliation_dash_has_screen_reader_text(self):
        response, html = self.clear_page()
        channels = response.context["cockpit"]["reconciliation"]["channels"]
        self.assertTrue(channels)
        self.assertTrue(all(not row["expected"] for row in channels))
        # T-296：待收合計依付款方式拆開四列，空資料時每列張數、金額的「—」都附讀螢幕文字。
        rows = response.context["cockpit"]["money"]["by_payment"]
        self.assertTrue(all(not row["count"] for row in rows))
        dash = '<span class="ops-money__nil" aria-hidden="true">—</span><span class="ops-visually-hidden">{}</span>'
        self.assertEqual(html.count(dash.format("0 張")), len(rows))
        self.assertEqual(html.count(dash.format("沒有金額")), len(rows))
        self.assertNotIn('<span class="ops-money__nil">—</span>', html)


class OperationsLayoutStylesTests(SimpleTestCase):
    def setUp(self):
        self.css = (Path(settings.BASE_DIR) / "static" / "css" / "operations.css").read_text(encoding="utf-8")

    def test_grid_rules(self):
        self.assertIn("grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);", self.css)   # 貨：油電領牌
        self.assertIn(".ops-row > :only-child", self.css)
        self.assertIn("@container ops-money-row (min-width: 48rem)", self.css)
        self.assertIn("container: ops-money / inline-size;", self.css)
        self.assertNotIn(".ops-stack", self.css)
        self.assertNotIn(".ops-row--wide", self.css)
        # 860 以下單欄，順序同桌面（不用 order 重排）。
        self.assertRegex(self.css, r"@media \(max-width: 860px\) \{[^@]*\.ops-row,\n  \.ops-row--stock \{\n"
                                   r"    grid-template-columns: minmax\(0, 1fr\);")
        self.assertNotRegex(self.css, r"\border:\s*-?\d")
