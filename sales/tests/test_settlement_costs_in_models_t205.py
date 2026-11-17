"""T-205（使用者 2026-11-17）：車輛結算成本搬進「機種與售價」。

網址不變，兩頁共用分頁列「機種與售價｜結算成本」；結算成本的資料、版本、計算與 costs 權限都不變。
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.access.registry import SCREEN_GROUPS
from sales.models import UserAppearancePreference, VehicleModel, VehicleSettlementCostRule
from sales.services.home_favorites import GROUPS
from sales.services.mobile_quick_links import MOBILE_QUICK_LINK_DEFINITIONS

TABS = 'aria-label="機種與售價分頁"'


class SettlementCostsInModelsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = get_user_model().objects.create_superuser("t205-root", password="Test-Only-123")
        cls.model = VehicleModel.objects.create(
            brand="SUZUKI", name="搬家甲", model_number="T205", model_year=2026,
            model_code=VehicleModel.ModelType.CBS_DISC, energy_type=VehicleModel.EnergyType.GAS, displacement_cc=125)
        cls.rule = VehicleSettlementCostRule.objects.create(vehicle_model=cls.model, amount=56000, effective_from=date(2026, 1, 1))
        cls.models_url = reverse("vehicle_model_list")
        cls.costs_url = reverse("settlement_cost_rule_list")

    def login(self, name=None, grants=None):
        if name is None:
            self.client.force_login(self.root)
            return self.root
        user = get_user_model().objects.create_user(name, password="Test-Only-123")
        UserAccessState.objects.create(user=user, configured=True)
        for key, operate in grants.items():
            ScreenAccessGrant.objects.create(user=user, screen_key=key, view=True, operate=operate)
        self.client.force_login(user)
        return user

    @staticmethod
    def tabs(response):
        html = response.content.decode()
        start = html.index(TABS)
        return html[start:html.index("</nav>", start)]

    def test_both_pages_share_tabs_and_cost_breadcrumb(self):
        self.login()
        models = self.client.get(self.models_url)
        tabs = self.tabs(models)
        self.assertIn(f'href="{self.models_url}" aria-current="page">機種與售價</a>', tabs)
        self.assertIn(f'href="{self.costs_url}">結算成本</a>', tabs)
        costs = self.client.get(self.costs_url)
        tabs = self.tabs(costs)
        self.assertIn(f'href="{self.models_url}">機種與售價</a>', tabs)
        self.assertIn(f'href="{self.costs_url}" aria-current="page">結算成本</a>', tabs)
        # 返回列：資料維護區 / 機種與售價 / 結算成本
        self.assertContains(costs, f'<li class="page-breadcrumb-root"><a href="{reverse("data_maintenance")}" data-return-to>資料維護區</a></li>', html=True)
        self.assertContains(costs, f'href="{self.models_url}" data-return-to aria-label="回到機種與售價"')
        self.assertContains(costs, 'data-current-page-label>結算成本</li>')
        # 資料與版本照舊列出，批次入口保留。
        self.assertContains(costs, "$56000")
        self.assertContains(costs, f'{reverse("vehicle_model_batch")}?dataset=cost&amp;from=costs')

    def test_old_urls_keep_working(self):
        self.login()
        for url in (self.costs_url, f"{self.costs_url}?q=T205", reverse("settlement_cost_rule_create"),
                    reverse("settlement_cost_rule_edit", args=[self.rule.pk]),
                    reverse("vehicle_model_settlement_costs", args=[self.model.pk])):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        self.assertContains(self.client.get(self.costs_url, {"q": "T205"}), "搬家甲")

    def test_models_only_user_sees_no_cost_tab(self):
        self.login("t205-models", {"models": True})
        page = self.client.get(self.models_url)
        self.assertNotContains(page, TABS)
        self.assertNotContains(page, self.costs_url)
        self.assertEqual(self.client.get(self.costs_url).status_code, 403)

    def test_costs_only_user_sees_only_cost_tab_and_entries(self):
        self.login("t205-costs", {"costs": True})
        self.assertEqual(self.client.get(self.models_url).status_code, 403)
        costs = self.client.get(self.costs_url)
        self.assertEqual(costs.status_code, 200)
        tabs = self.tabs(costs)
        self.assertNotIn(self.models_url, tabs)
        self.assertIn(f'href="{self.costs_url}" aria-current="page">結算成本</a>', tabs)
        self.assertContains(costs, f'href="{reverse("data_maintenance")}" data-return-to aria-label="回到資料維護區"')
        self.assertNotContains(costs, f'{reverse("vehicle_model_batch")}?dataset=cost')
        # 頁首選單與資料維護區仍有入口，指向結算成本。
        menu = costs.content.decode().split('aria-label="資料維護選單"', 1)[1].split("</div>", 1)[0]
        self.assertIn(f'<a href="{self.costs_url}"><strong>機種與售價・結算成本</strong>', menu)
        maintenance = self.client.get(reverse("data_maintenance"))
        self.assertContains(maintenance, f'<a class="maintenance-card" href="{self.costs_url}">')
        self.assertContains(maintenance, "<h2>機種與售價・結算成本</h2>")

    def test_header_menu_and_data_maintenance_have_no_separate_cost_entry(self):
        self.login()
        page = self.client.get(reverse("data_maintenance"))
        menu = page.content.decode().split('aria-label="資料維護選單"', 1)[1].split("</div>", 1)[0]
        self.assertNotIn(self.costs_url, menu)
        self.assertNotIn("車輛結算成本", menu)
        self.assertNotContains(page, f'<a class="maintenance-card" href="{self.costs_url}">')
        self.assertNotContains(page, "<h2>車輛結算成本</h2>")
        self.assertContains(page, f'<a class="maintenance-card" href="{self.models_url}">')

    def test_quick_links_favorites_and_permission_group(self):
        keys = [item["key"] for item in MOBILE_QUICK_LINK_DEFINITIONS]
        cost = next(item for item in MOBILE_QUICK_LINK_DEFINITIONS if item["key"] == "settlement-costs")
        self.assertEqual(cost["label"], "機種與售價・結算成本")
        self.assertEqual(cost["route"], "settlement_cost_rule_list")
        self.assertEqual(keys.index("settlement-costs"), keys.index("vehicle-models") + 1)
        groups = {key: links for key, _title, _desc, links in GROUPS}
        self.assertIn("settlement-costs", groups["vehicles"])
        self.assertNotIn("settlement-costs", groups["rules"])
        self.assertEqual(groups["vehicles"].index("settlement-costs"), groups["vehicles"].index("vehicle-models") + 1)
        data = {title: screens for title, screens in next(g for g in SCREEN_GROUPS if g[0] == "data")[2]}
        self.assertIn("costs", data["車輛與商品"])
        self.assertNotIn("costs", data["費率與規則"])
        # 已經加進常用功能與手機捷徑的人，連結照樣能用。
        user = self.login()
        UserAppearancePreference.objects.update_or_create(
            user=user, defaults={"home_favorites": ["settlement-costs"], "mobile_quick_links": ["settlement-costs"]})
        home = self.client.get(reverse("dashboard"))
        self.assertEqual([item["key"] for item in home.context["favorite_links"]], ["settlement-costs"])
        self.assertEqual(home.context["favorite_links"][0]["url"], self.costs_url)
        self.assertEqual([item["url"] for item in home.context["mobile_quick_links"]], [self.costs_url])

    def test_help_articles_moved_cost_routes(self):
        from sales.help import ARTICLES
        by_slug = {article.slug: article for article in ARTICLES}
        models, incentives = by_slug["vehicle-models"], by_slug["incentives"]
        self.assertEqual(incentives.title, "原廠獎勵與補助方案")
        for route in ("settlement_cost_rule_list", "settlement_cost_rule_create", "settlement_cost_rule_edit"):
            self.assertIn(route, models.routes)
            self.assertNotIn(route, incentives.routes)
        self.assertIn("結算成本請看〈機種、售價與年式〉", " ".join(step.text for step in incentives.steps))
        self.assertIn("[[結算成本]]", " ".join(step.text for step in models.steps))
