"""營運總表「錢」車行未付（使用者 2026-11-23）。

「車行掛帳」改名「車行未付」，小字只寫「N 家共 M 張」，不再提額度
（舊寫法「1 家・1 張，1 家未設額度」看起來像三間）。金額、張數、連結不變。
T-301（使用者 2026-11-24）：「已含在交車後未結清」小標籤拿掉，頁面上不再出現這句。
"""
from django.urls import reverse

from sales.tests.test_money_card_t278 import DealerCreditLinkTests, MoneyCardTestBase

NOTE = '<dt>車行未付{}'


class DealerUnpaidNoteTests(MoneyCardTestBase):
    on_account = DealerCreditLinkTests.on_account

    def card(self):
        response, cockpit = self.cockpit()
        html = response.content.decode()
        start = html.index("<dt>車行未付")
        return response, cockpit, html[start:html.index("</dd>", start)]

    def assert_note(self, counts):
        response, _cockpit, row = self.card()
        self.assertContains(response, NOTE.format(counts))
        self.assertNotContains(response, "已含在交車後未結清")
        self.assertNotIn("車行掛帳", row)
        self.assertNotIn("額度", row)
        return row

    def test_single_dealer(self):
        self.on_account(self.dealer)
        self.assert_note("<small class=\"ops-facts__note\"><span class=\"ops-facts__note-count\">1 家共 1 張</span></small>")

    def test_several_dealers_count_dealers_and_orders(self):
        # T-288 額度移除：原本「混合額度」的情況不存在了，改驗多家多張時家數、張數照算、不提額度。
        self.on_account(self.dealer)
        self.on_account(self.dealer)
        self.on_account(self.other_dealer)
        self.assert_note("<small class=\"ops-facts__note\"><span class=\"ops-facts__note-count\">2 家共 3 張</span></small>")

    def test_all_dealers_without_limit(self):
        self.on_account(self.dealer)
        self.on_account(self.other_dealer)
        self.assert_note("<small class=\"ops-facts__note\"><span class=\"ops-facts__note-count\">2 家共 2 張</span></small>")

    def test_amount_and_link_unchanged(self):
        self.on_account(self.dealer)
        self.on_account(self.other_dealer)
        _response, cockpit, row = self.card()
        url = reverse("operations_dealer_credit") + "?scope=all"
        self.assertIn(f'href="{url}"', row)
        self.assertIn(f'${int(cockpit["money"]["dealer_credit_total"]):,}', row)

    def test_none(self):
        response, _cockpit, row = self.card()
        self.assertContains(response, NOTE.format("</dt>"))
        self.assertNotContains(response, "已含在交車後未結清")
        self.assertIn("目前沒有", row)

    def test_list_page_renamed(self):
        self.on_account(self.dealer)
        page = self.client.get(reverse("operations_dealer_credit") + "?scope=all")
        self.assertContains(page, "<h1>車行未付</h1>", html=False)
        self.assertNotContains(page, "車行掛帳")
        self.assertContains(page, "未付 <strong>")
