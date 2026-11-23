"""營運總表「錢」車行未付（使用者 2026-11-23）。

「車行掛帳」改名「車行未付」，小字只寫「已含在交車後未結清 · N 家共 M 張」，不再提額度
（舊寫法「1 家・1 張，1 家未設額度」看起來像三間）。金額、張數、連結不變。
"""
from decimal import Decimal

from django.urls import reverse

from sales.tests.test_money_card_t278 import DealerCreditLinkTests, MoneyCardTestBase

NOTE = '車行未付<small class="ops-facts__note">已含在交車後未結清{}</small>'


class DealerUnpaidNoteTests(MoneyCardTestBase):
    on_account = DealerCreditLinkTests.on_account

    def set_limit(self, dealer, limit):
        dealer.credit_limit = limit
        dealer.save(update_fields=["credit_limit"])

    def card(self):
        response, cockpit = self.cockpit()
        html = response.content.decode()
        start = html.index("車行未付<small")
        return response, cockpit, html[start:html.index("</dd>", start)]

    def assert_note(self, counts):
        response, _cockpit, row = self.card()
        self.assertContains(response, NOTE.format(counts))
        self.assertNotIn("車行掛帳", row)
        self.assertNotIn("額度", row)
        return row

    def test_single_dealer(self):
        self.on_account(self.dealer)
        self.assert_note(" · <span class=\"ops-facts__note-count\">1 家共 1 張</span>")

    def test_several_dealers_mixed_limits_mention_no_limit(self):
        self.set_limit(self.dealer, Decimal("1"))                      # 超額
        self.set_limit(self.other_dealer, Decimal("10000000"))        # 有額度沒超
        self.on_account(self.dealer)
        self.on_account(self.dealer)
        self.on_account(self.other_dealer)
        self.assert_note(" · <span class=\"ops-facts__note-count\">2 家共 3 張</span>")

    def test_all_dealers_without_limit(self):
        self.on_account(self.dealer)
        self.on_account(self.other_dealer)
        self.assert_note(" · <span class=\"ops-facts__note-count\">2 家共 2 張</span>")

    def test_amount_and_link_unchanged(self):
        self.on_account(self.dealer)
        self.on_account(self.other_dealer)
        _response, cockpit, row = self.card()
        url = reverse("operations_dealer_credit") + "?scope=all"
        self.assertIn(f'href="{url}"', row)
        self.assertIn(f'${int(cockpit["money"]["dealer_credit_total"]):,}', row)

    def test_none(self):
        response, _cockpit, row = self.card()
        self.assertContains(response, NOTE.format(""))
        self.assertIn("目前沒有", row)

    def test_list_page_renamed(self):
        self.on_account(self.dealer)
        page = self.client.get(reverse("operations_dealer_credit") + "?scope=all")
        self.assertContains(page, "<h1>車行未付</h1>", html=False)
        self.assertNotContains(page, "車行掛帳")
        self.assertContains(page, "未付 <strong>")
