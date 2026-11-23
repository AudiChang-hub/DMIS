"""T-295（使用者 2026-11-23）：營運總表「錢」三張卡依時間排，0 張時金額寫 $0。

- 順序：未交車・尾款待收 → 已交車待撥款 → 交車後未結清（桌面左到右、手機上到下，DOM 順序即閱讀順序）；
  待收合計分段長條、「怎麼算的」算式跟著同樣順序。帳齡長條是交車後未結清專用，位置不動。
- 0 張的卡右上角金額寫「$0」，三張卡標題列對齊；沒有 operations 權限照舊不出現金額。只改顯示，數字不變。
"""
import re

from django.contrib.auth import get_user_model
from django.urls import reverse

from sales.models import ScreenAccessGrant, UserAccessState
from sales.tests.test_money_card_t278 import MoneyCardTestBase

CARD = re.compile(r'<div class="ops-fig ops-money__card ops-money__card--(\w+)"><h3 class="ops-money__label"><span>[^<]+'
                  r'</span></h3><p class="ops-money__sum">(.*?)</p>', re.S)


class MoneyCardOrderZeroTests(MoneyCardTestBase):

    def section(self, response):
        html = response.content.decode()
        start = html.index('aria-labelledby="ops-money-title"')
        return html[start:html.index("</section>", start)]

    def sums(self, response):
        return [(key, re.findall(r'<span class="ops-money__amount">([^<]*)</span>', body))
                for key, body in CARD.findall(self.section(response))]

    def test_cards_bar_and_formula_follow_time_order(self):
        self.order("delivery_pending", source_type="store", source=self.staff)
        response, cockpit = self.cockpit()
        html = self.section(response)
        self.assertEqual([key for key, _ in CARD.findall(html)], ["before", "awaiting", "unsettled"])
        self.assertEqual([term["label"] for term in cockpit["money"]["outstanding_terms"]],
                         ["未交車・尾款待收", "已交車待撥款", "交車後未結清"])
        label = re.search(r'class="ops-money__stack" role="img" aria-label="([^"]+)"', html).group(1)
        self.assertLess(label.index("未交車・尾款待收"), label.index("已交車待撥款"))
        self.assertLess(label.index("已交車待撥款"), label.index("交車後未結清"))
        # 帳齡長條仍在卡片、待收合計之後，標題照舊。
        self.assertLess(html.index('class="ops-money__total"'), html.index("交車後未結清 · 帳齡（交車日起）"))

    def test_zero_cards_show_zero_amount(self):
        self.order("delivery_pending", source_type="store", source=self.staff)
        response, cockpit = self.cockpit()
        money = cockpit["money"]
        self.assertEqual((money["before_delivery_count"], money["awaiting_payout_count"], money["unsettled_count"]),
                         (1, 0, 0))
        self.assertEqual(self.sums(response), [("before", [f"${int(money['before_delivery_amount']):,}"]),
                                               ("awaiting", ["$0"]), ("unsettled", ["$0"])])

    def test_all_zero_cards_show_zero_amount(self):
        response, _cockpit = self.cockpit()
        self.assertEqual(self.sums(response), [("before", ["$0"]), ("awaiting", ["$0"]), ("unsettled", ["$0"])])

    def test_viewer_without_operations_gets_no_card_amounts(self):
        self.order("delivery_pending", source_type="store", source=self.staff)
        user = get_user_model().objects.create_user("t295-dashboard", password="test-only")
        UserAccessState.objects.create(user=user, configured=True)
        ScreenAccessGrant.objects.create(user=user, screen_key="dashboard", view=True)
        self.client.force_login(user)
        response = self.client.get(reverse("operations_report"))
        self.assertEqual(self.sums(response), [("before", []), ("awaiting", []), ("unsettled", [])])
