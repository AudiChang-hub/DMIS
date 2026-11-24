"""T-289 訂單總覽區塊位置固定：每張單同一組區塊、同一位置、同一順序，資料少也照樣輸出。

T-307 起兩欄固定指派（OVERVIEW_COLUMNS）改為卡片成對排列（OVERVIEW_PAIRS），備註改成標題區便條紙；
「位置固定」的檢查改對成對順序。
"""
import re
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from sales.models import AccessoryLine, PaymentRecord, SalesOrder
from sales.services.order_overview import NOTE_KEY, OVERVIEW_PAIRS, build_order_overview
from sales.tests import test_order_lifecycle as lifecycle

CORE_SECTIONS = ["order", "owner", "vehicle", "registration", "price", "installment", "delivery", "note"]
# T-307 畫面順序：一列兩張（左｜右），備註不是卡片。
CARD_ORDER = ["owner", "vehicle", "registration", "trade_in", "order", "price", "installment", "delivery",
              "dealer_reward", "cancellation"]


class OrderOverviewLayoutTests(TestCase):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def sparse_order(self):
        """現金、沒有加購、沒有收支、沒有備註。"""
        order, _vehicle = self.make_order(deposit=Decimal("0"))
        order.payment_records.all().delete()
        order.accessories.all().delete()
        return SalesOrder.objects.get(pk=order.pk)

    def rich_order(self):
        """分期、有加購、汰舊、長備註、有收支。"""
        order, _vehicle = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(
            payment_type=SalesOrder.PaymentType.INSTALLMENT, installment_company="示範分期", installment_periods=24,
            installment_amount=Decimal("60000"), installment_monthly=Decimal("2800"),
            is_trade_in_subsidy=True, trade_in_plate="ABC-123", note="長備註" * 80,
        )
        AccessoryLine.objects.create(order=order, name="後架", quantity=1, amount=Decimal("1200"))
        PaymentRecord.objects.create(order=order, item_name="訂金", expected_amount=Decimal("5000"), received_amount=Decimal("5000"))
        return SalesOrder.objects.get(pk=order.pk)

    def keys(self, overview):
        return [section["key"] for section in overview["sections"]]

    def test_sparse_order_still_lists_every_core_section_and_table(self):
        overview = build_order_overview(self.sparse_order())
        # T-292：情境區塊與明細表也一律輸出。
        self.assertEqual(self.keys(overview), ["order", "owner", "vehicle", "registration", "dealer_reward", "price",
                                               "installment", "trade_in", "delivery", "cancellation", "note"])
        self.assertEqual([table["key"] for table in overview["tables"]], ["accessories", "fees", "subsidies", "payments"])
        installment = next(section for section in overview["sections"] if section["key"] == "installment")
        self.assertTrue(all(row["value"] == "—" and row["copy"] == "" for row in installment["rows"]))
        # 「複製全部」照舊只帶有資料的欄位：空的分期、空明細表不出現。
        self.assertNotIn("【分期】", overview["plain_text"])
        self.assertNotIn("【加購項目與贈品】", overview["plain_text"])
        self.assertNotIn("【收入與支出】", overview["plain_text"])
        self.assertNotIn("【其他費用】", overview["plain_text"])
        self.assertNotIn("【補助項目】", overview["plain_text"])

    def test_cards_are_paired_in_fixed_order_regardless_of_content(self):
        sparse = build_order_overview(self.sparse_order())
        rich = build_order_overview(self.rich_order())
        for overview in (sparse, rich):
            self.assertEqual([section["key"] for section in overview["cards"]], CARD_ORDER)
            self.assertNotIn(NOTE_KEY, [section["key"] for section in overview["cards"]])
            # 「複製全部」的區塊順序（sections）不跟著畫面改。
            self.assertEqual([key for key in self.keys(overview) if key in CORE_SECTIONS], CORE_SECTIONS)
        self.assertEqual([key for pair in OVERVIEW_PAIRS for key in pair], CARD_ORDER)
        self.assertTrue(all(len(pair) == 2 for pair in OVERVIEW_PAIRS))

    def test_rows_inside_each_core_section_are_fixed(self):
        sparse = build_order_overview(self.sparse_order())
        rich = build_order_overview(self.rich_order())
        labels = lambda overview, key: [row["label"] for row in next(s for s in overview["sections"] if s["key"] == key)["rows"]]
        for key in CORE_SECTIONS:
            self.assertEqual(labels(sparse, key), labels(rich, key), key)
        price = {row["label"]: row for row in next(s for s in sparse["sections"] if s["key"] == "price")["rows"]}
        self.assertEqual((price["牌險"]["value"], price["牌險"]["copy"]), ("—", ""))
        self.assertEqual(price["分期外應收"]["value"], "—")

    def test_page_renders_paired_cards_and_jump_in_card_order(self):
        self.client.force_login(self.user)
        for order in (self.sparse_order(), self.rich_order()):
            page = self.client.get(reverse("order_overview", args=[order.pk]) + "?fragment=1").content.decode()
            pairs = page.split('class="order-overview__pairs"', 1)[1].split('class="order-overview__tables"', 1)[0]
            ids = re.findall(r'<section class="order-overview__card" id="overview-(\w+)"', pairs)
            self.assertEqual(ids, CARD_ORDER)
            jumps = re.findall(r'<a href="#overview-(\w+)" data-overview-jump>', page)
            self.assertEqual(jumps, CARD_ORDER + ["accessories", "fees", "subsidies", "payments"])
            self.assertNotIn('id="overview-note"', page)
        self.assertIn("沒有加購項目或贈品", self.client.get(reverse("order_overview", args=[self.sparse_order().pk])).content.decode())

    def test_css_uses_fixed_pairs_not_masonry(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "order-overview.css").read_text(encoding="utf-8")
        # 不用多欄瀑布流（CSS columns 依卡片高度分欄，每張單排列不同）。
        # columns: 可能是區塊第一個屬性，也可能接在 ; 後面；grid-template-columns 不算。
        masonry = r"\.order-overview__(grid|pairs) \{(?:[^}]*;)?\s*columns:"
        self.assertRegex(".order-overview__grid { columns: 2 320px; }", masonry)
        self.assertRegex(".order-overview__pairs { gap: 1rem; columns: 2; }", masonry)
        self.assertNotRegex(".order-overview__grid { grid-template-columns: 1fr 1fr; }", masonry)
        self.assertNotRegex(css, masonry)
        self.assertIn("@container order-overview-grid (min-width: 700px)", css)
        self.assertRegex(css, r"\.order-overview__pairs \{ display: grid; grid-template-columns: repeat\(2, minmax\(0, 1fr\)\); align-items: stretch;")

    def test_every_section_has_a_place_and_every_jump_has_a_rendered_section(self):
        """新增區塊忘了加進 OVERVIEW_PAIRS 會從畫面消失：這裡把兩邊對齊（備註在標題區便條紙）。"""
        from unittest import mock
        from django.utils import timezone

        # 原始碼裡所有 _section("key", ...) 都要有位置（成對卡片或便條紙），且只出現一次。
        source = (Path(settings.BASE_DIR) / "sales" / "services" / "order_overview.py").read_text(encoding="utf-8")
        declared = set(re.findall(r'_section\("(\w+)"', source))
        assigned = [key for pair in OVERVIEW_PAIRS for key in pair] + [NOTE_KEY]
        self.assertEqual(len(assigned), len(set(assigned)))
        self.assertEqual(set(assigned), declared)

        # 情境區塊全部出現的單（汰舊、取消與退款、車行獎勵）：卡片數＋便條紙＝區塊數，跳轉按鈕與卡片一一對得到。
        order = self.rich_order()
        SalesOrder.objects.filter(pk=order.pk).update(cancellation_requested_at=timezone.now(), cancellation_reason="客人改買他牌")
        order = SalesOrder.objects.get(pk=order.pk)
        reward = {"key": "dealer_reward", "title": "車行獎勵", "rows": [{"label": "傭金", "value": "$1,500", "copy": "1500", "wide": False, "mono": True}]}
        with mock.patch("sales.services.order_overview._dealer_reward_section", return_value=reward):
            overview = build_order_overview(order)
            self.client.force_login(self.user)
            page = self.client.get(reverse("order_overview", args=[order.pk]) + "?fragment=1").content.decode()
        keys = self.keys(overview)
        self.assertEqual(set(keys), declared)
        self.assertEqual(len(overview["cards"]) + 1, len(keys))
        self.assertEqual(sorted([section["key"] for section in overview["cards"]] + [NOTE_KEY]), sorted(keys))
        jumps = re.findall(r'<a href="#overview-(\w+)" data-overview-jump>', page)
        rendered = re.findall(r'<section class="order-overview__card[^"]*" id="overview-(\w+)"', page)
        table_keys = [table["key"] for table in overview["tables"]]
        self.assertEqual(len(jumps), len(overview["cards"]) + len(table_keys))
        self.assertEqual(sorted(jumps), sorted(rendered))
        self.assertIn("cancellation", jumps)
        self.assertIn("dealer_reward", jumps)
