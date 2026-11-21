"""T-277（使用者 2026-11-21）：給付頁摘要。

- 「列入範圍」大字寫明更早的 Excel 匯入單列為匯入前已結清，小字不重複；空狀態說明一致。
- 「已給付金額」＝一般已給付＋匯入前已結清，小字註明含多少匯入前已結清；套篩選後同一算法。
"""
from decimal import Decimal

from django.urls import reverse

from sales.reporting import payouts
from sales.tests.test_dealer_payouts_t150 import KEY
from sales.tests.test_legacy_payouts_t275 import LegacyPayoutBase

RANGE = '<dd class="payout-summary__range">2026/10/05 起領牌，更早的 Excel 匯入單列為匯入前已結清</dd>'
PRIOR = "更早的 Excel 匯入單"


class PayoutRangeTextTests(LegacyPayoutBase):
    def page(self):
        self.client.force_login(self.admin)
        return self.client.get(reverse("dealer_payout_list")).content.decode()

    def test_range_headline_mentions_prior_settled_imports_once(self):
        self.imported()
        page = self.page()
        self.assertIn(RANGE, page)
        self.assertEqual(page.count(PRIOR), 1)  # 下面小字不再重複

    def test_empty_state_matches_range(self):
        page = self.page()
        self.assertIn(RANGE, page)
        self.assertIn("目前沒有要給車行的項目", page)
        self.assertIn("2026/10/05 起領牌完成的車行單", page)
        self.assertIn("更早的 Excel 匯入單列為匯入前已結清", page.split("目前沒有要給車行的項目")[1])


class PaidTotalTests(LegacyPayoutBase):
    """使用者 2026-11-21：「已給付金額應該要全部加總」＝一般已給付＋匯入前已結清；套篩選後同一算法。"""

    def setUp(self):
        super().setUp()
        self.system = self.registered()  # 系統車行單傭金 2,300，勾已給付
        payouts.set_paid([KEY.format(self.system.pk)], True, "staffb")
        self.prior = self.imported()  # 10/05 前領牌的匯入車行單，四欄加總 6,200
        self.unpaid = self.registered()  # 另一張未給付 2,300，不算進已給付

    def test_totals_split_and_sum(self):
        totals = payouts.totals(payouts.collect_items())
        self.assertEqual(totals["paid_amount"], Decimal("2300"))
        self.assertEqual((totals["prior_settled_count"], totals["prior_settled_amount"]), (1, Decimal("6200")))
        self.assertEqual(totals["paid_total_amount"], Decimal("8500"))
        self.assertEqual((totals["unpaid_amount"], totals["unpaid_count"]), (Decimal("2300"), 1))  # 不變

    def test_filtered_totals_use_same_rule(self):
        items = payouts.collect_items()
        for status, paid, prior in (("paid", "2300", "0"), ("prior_settled", "0", "6200"), ("unpaid", "0", "0")):
            with self.subTest(status=status):
                totals = payouts.totals(payouts.filter_items(items, status=status))
                self.assertEqual(totals["paid_amount"], Decimal(paid))
                self.assertEqual(totals["prior_settled_amount"], Decimal(prior))
                self.assertEqual(totals["paid_total_amount"], Decimal(paid) + Decimal(prior))

    def test_page_shows_sum_with_prior_settled_note(self):
        self.client.force_login(self.admin)
        page = self.client.get(reverse("dealer_payout_list")).content.decode()
        self.assertIn("<dt>已給付金額</dt><dd>$8,500</dd><small>含匯入前已結清 1 項 · $6,200</small>", page)
        self.assertNotIn("另有匯入前已結清", page)
        page = self.client.get(reverse("dealer_payout_list") + "?status=paid").content.decode()
        self.assertIn("<dt>已給付金額</dt><dd>$2,300</dd></div>", page)  # 篩選後沒有匯入前已結清就不顯示小字
