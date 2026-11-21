"""T-277（使用者 2026-11-21）：給付頁「列入範圍」大字寫明更早的 Excel 匯入單列為匯入前已結清，小字不重複；空狀態說明一致。"""
from django.urls import reverse

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
