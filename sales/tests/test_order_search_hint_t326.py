"""T-326：全部訂單搜尋提示，車型只有在關鍵字落在列上被截掉的那段時才列出。

列上的機種欄（所屬機種名稱，存檔時依車型名稱連到同名機種）截成 10 字（_compact_text limit=10，顯示前 9 字加「…」）。
T-319 把車型當成「列上已顯示」一律不列，關鍵字在被截掉的那段就沒有任何提示。資料全部虛構。
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from sales.services import order_search
from sales.services.order_search import order_match_terms, rebuild_order_search_index
from sales.tests import test_order_flow  # 只借 setUp／make_order

LONG_NAME = "示範長名車型 125 ABS 碟煞版"  # 列上看得到「示範長名車型 12」


class OrderSearchModelHintTests(TestCase):
    setUp = test_order_flow.OrderFlowTests.setUp
    make_order = test_order_flow.OrderFlowTests.make_order

    def condense(self, order, query):
        matches = [{"label": "車型", "value": order.vehicle_model.name}]
        shown, more = order_search.condense_order_matches(order, matches, order_match_terms(query))
        return [(item["label"], item["hit"]) for item in shown], more

    def long_name_order(self):
        self.model.name = LONG_NAME
        self.model.save(update_fields=["name"])
        return self.make_order()

    def test_keyword_in_the_cut_off_part_is_listed(self):
        order = self.long_name_order()
        self.assertEqual(self.condense(order, "碟煞"), ([("車型", "碟煞")], 0))
        self.assertEqual(self.condense(order, "abs"), ([("車型", "ABS")], 0))

    def test_keyword_still_visible_after_truncation_is_not_listed(self):
        order = self.long_name_order()
        for query in ("示範長名", "車型 12"):
            with self.subTest(query=query):
                self.assertEqual(self.condense(order, query), ([], 0))

    def test_keyword_cut_in_half_by_truncation_is_listed(self):
        order = self.long_name_order()
        self.assertEqual(self.condense(order, "125"), ([("車型", "125")], 0))

    def test_short_model_name_is_fully_visible_and_not_listed(self):
        order = self.make_order()
        self.assertEqual(self.condense(order, "125"), ([], 0))

    def test_only_model_hint_is_flagged_compact_only(self):
        order = self.long_name_order()
        matches = [{"label": "車型", "value": LONG_NAME}, {"label": "備註", "value": "客人想要碟煞版"}]
        shown, _ = order_search.condense_order_matches(order, matches, order_match_terms("碟煞"))
        self.assertEqual([(item["label"], item["compact_only"]) for item in shown], [("車型", True), ("備註", False)])

    def test_order_list_shows_model_hint_only_when_cut_off(self):
        order = self.long_name_order()
        rebuild_order_search_index(order.pk)
        self.client.force_login(self.user)
        response = self.client.get(reverse("order_list"), {"q": "碟煞"})
        row = response.context["orders"][0]
        self.assertEqual(row.pk, order.pk)
        self.assertEqual(row.search_matches[0]["label"], "車型")
        self.assertTrue(row.search_matches[0]["compact_only"])
        html = response.content.decode()
        # 手機卡片一律顯示機種全名、表格超過 1440 寬也是全名：車型提示加上 class，由 CSS 在這兩處藏起來。
        self.assertIn('<span class="search-match search-match--compact-only"><b>車型</b><span class="search-match__text">', html)
        self.assertIn('<span class="search-match--compact-only">車型：', html)
        self.assertIn("<mark>碟煞</mark>", html)
        response = self.client.get(reverse("order_list"), {"q": "示範長名"})
        self.assertNotIn("車型", [match["label"] for match in response.context["orders"][0].search_matches])


class SearchMatchCompactOnlyCssTests(TestCase):
    def test_model_hint_is_hidden_where_the_full_name_is_shown(self):
        css = (Path(settings.BASE_DIR) / "static/css/order-list.css").read_text(encoding="utf-8")
        self.assertIn(".order-row--detailed .search-match--compact-only,", css)
        wide = css[css.index("@media (min-width: 1440.02px)"):]
        self.assertIn(".order-sort-table td .search-match-list > .search-match--compact-only,", wide[:wide.index("}")])
        app = (Path(settings.BASE_DIR) / "static/css/app.css").read_text(encoding="utf-8")
        self.assertRegex(app, r"@media\(max-width:1440px\)\{\s*\.compact-text-wide\{display:none\}", "截短的斷點要和 app.css 一致")


class SearchMatchSpacingTokenTests(TestCase):
    def test_search_match_text_padding_uses_spacing_tokens(self):
        css = (Path(settings.BASE_DIR) / "static/css/order-list.css").read_text(encoding="utf-8")
        rule = re.search(r"\.search-match__text \{([^}]*)\}", css).group(1)
        padding = re.search(r"padding:\s*([^;]+);", rule).group(1)
        self.assertEqual(padding.strip(), "var(--space-1) var(--space-2)")
        self.assertNotRegex(padding, r"\d+px")
