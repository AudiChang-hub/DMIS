"""T-162：車行傭金與獎勵四頁收成一個入口＋共用分頁列；分頁依原本的畫面權限顯示，網址不變。"""
import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState

TAB_NAV = re.compile(r'<nav class="account-tabs dealer-reward-tabs" aria-label="車行傭金與獎勵">(.*?)</nav>', re.S)
MENU_RULES = re.compile(r'<h2 id="data-menu-rules">費率與規則</h2>(.*?)</section>', re.S)
OLD_TITLES = ("車行傭金與銷售獎勵", "車行獎勵活動", "車行獎勵品項", "車行台數獎金")


class DealerRewardEntryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = get_user_model().objects.create_superuser("admin", password="Test-Only-123")
        cls.user = get_user_model().objects.create_user("limited", password="Test-Only-123")
        UserAccessState.objects.create(user=cls.user, configured=True)

    def grant(self, *keys):
        for key in keys:
            ScreenAccessGrant.objects.create(user=self.user, screen_key=key, view=True)
        self.client.force_login(self.user)

    def tabs(self, response):
        nav = TAB_NAV.search(response.content.decode())
        self.assertIsNotNone(nav)
        return re.findall(r'<a href="([^"]+)"( aria-current="page")?>([^<]+)</a>', nav[1])

    def menu_entry(self, response):
        rules = MENU_RULES.search(response.content.decode())[1]
        return re.findall(r'<a href="([^"]+)"><strong>車行傭金與獎勵</strong><small>基礎傭金、獎勵活動與品項、台數獎金</small></a>', rules)

    def test_all_four_pages_share_tabs_and_mark_current(self):
        self.client.force_login(self.root)
        pages = (("dealer_sales_program_list", "基礎傭金"), ("dealer_reward_campaign_list", "獎勵活動"),
                 ("dealer_reward_catalog_list", "獎勵品項"), ("dealer_volume_bonus_list", "台數獎金"))
        expected = [(reverse(name), label) for name, label in pages]
        for name, label in pages:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                tabs = self.tabs(response)
                self.assertEqual([(url, text) for url, _, text in tabs], expected)
                self.assertEqual([text for _, current, text in tabs if current], [label])

    def test_tabs_and_entry_follow_existing_screen_keys(self):
        self.grant("bonuses")
        response = self.client.get(reverse("dealer_volume_bonus_list"))
        self.assertEqual([text for _, _, text in self.tabs(response)], ["台數獎金"])
        self.assertEqual(self.menu_entry(response), [reverse("dealer_volume_bonus_list")])
        self.assertEqual(self.client.get(reverse("dealer_sales_program_list")).status_code, 403)

    def test_entry_goes_to_first_permitted_tab(self):
        self.grant("commissions", "rewards")
        response = self.client.get(reverse("dealer_reward_catalog_list"))
        self.assertEqual([text for _, _, text in self.tabs(response)], ["基礎傭金", "獎勵活動", "獎勵品項"])
        self.assertEqual(self.menu_entry(response), [reverse("dealer_sales_program_list")])

    def test_menu_and_data_home_show_one_entry_only(self):
        self.client.force_login(self.root)
        response = self.client.get(reverse("data_maintenance"))
        html = response.content.decode()
        rules = MENU_RULES.search(html)[1]
        self.assertEqual(self.menu_entry(response), [reverse("dealer_sales_program_list")])
        for title in OLD_TITLES:
            self.assertNotIn(f"<strong>{title}</strong>", rules)
            self.assertNotIn(f"<h2>{title}</h2>", html)
        self.assertNotIn("逐單結算", html)
        self.assertEqual(html.count("<h2>車行傭金與獎勵</h2>"), 1)
