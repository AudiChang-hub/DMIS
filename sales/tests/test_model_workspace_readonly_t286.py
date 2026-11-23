"""T-286：機種工作區「傭金與獎勵」「結算成本」「原廠獎勵與補助」只能看；基礎傭金改在「車行傭金與銷售獎勵」逐列設定。"""
import re
from datetime import date
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import IncentiveCampaign, VehicleModel, VehicleSettlementCostRule

POST_FORM = re.compile(r"<form[^>]*method=\"post\"", re.IGNORECASE)


class WorkspaceReadOnlyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = get_user_model().objects.create_superuser("t286-root", password="Test-Only-123")
        cls.model = VehicleModel.objects.create(
            brand="SUZUKI", name="T286 測試車", model_number="T286DA", model_year=2026,
            energy_type=VehicleModel.EnergyType.GAS, displacement_cc=125, base_dealer_commission=Decimal("1500"),
        )
        cls.rule = VehicleSettlementCostRule.objects.create(
            vehicle_model=cls.model, amount=Decimal("56000"), effective_from=date(2026, 1, 1),
            announced_on=date(2025, 12, 20), note="T286 成本備註",
        )
        cls.campaign = IncentiveCampaign.objects.create(name="T286 常態獎勵", sales_bonus=1000,
                                                        effective_from=date(2026, 1, 1))
        cls.campaign.vehicle_models.set([cls.model])

    def setUp(self):
        self.client.force_login(self.root)

    def url(self, name):
        return reverse(name, args=[self.model.pk])

    def test_three_tabs_have_no_post_form_or_inputs(self):
        for name in ("vehicle_model_commission", "vehicle_model_settlement_costs", "vehicle_model_incentives"):
            with self.subTest(tab=name):
                html = self.client.get(self.url(name)).content.decode()
                main = html.split('<main', 1)[1]
                self.assertIsNone(POST_FORM.search(main))
                self.assertNotIn('name="base_dealer_commission"', main)
                self.assertNotIn('name="amount"', main)
                self.assertNotIn('name="effective_from"', main)
                self.assertNotIn("data-active-toggle", main)

    def test_tabs_keep_showing_current_settings(self):
        commission = self.client.get(self.url("vehicle_model_commission"))
        self.assertContains(commission, "$1500")
        self.assertContains(commission, "沒有版本，設定後立即生效")
        costs = self.client.get(self.url("vehicle_model_settlement_costs"))
        for text in ("$56000", "2026/01/01 起", "2025/12/20", "T286 成本備註", "生效中", "未設定結束日"):
            self.assertContains(costs, text)
        incentives = self.client.get(self.url("vehicle_model_incentives"))
        self.assertContains(incentives, "T286 常態獎勵")

    def test_tabs_link_to_dedicated_pages_with_this_model(self):
        query = urlencode({"q": "T286DA"})
        commission = self.client.get(self.url("vehicle_model_commission"))
        self.assertContains(commission, f'href="{reverse("dealer_sales_program_list")}?{query}#program-{self.model.pk}"')
        self.assertContains(commission, f'href="{reverse("dealer_reward_campaign_list")}"')
        self.assertContains(commission, f'{reverse("dealer_reward_campaign_create")}?model={self.model.pk}')
        costs = self.client.get(self.url("vehicle_model_settlement_costs"))
        self.assertContains(costs, f'href="{reverse("settlement_cost_rule_list")}?{query}"')
        inactive_costs = self.client.get(self.url("vehicle_model_settlement_costs"), {"status": "inactive"})
        self.assertContains(inactive_costs, f'href="{reverse("settlement_cost_rule_list")}?{query}&amp;status=inactive"')
        incentives = self.client.get(self.url("vehicle_model_incentives"))
        self.assertContains(incentives, f'href="{reverse("incentive_rule_list")}"')
        self.assertContains(incentives, f'{reverse("incentive_campaign_create")}?model={self.model.pk}')
        # 帶入的搜尋條件在專屬頁確實找得到本機種。
        listing = self.client.get(f'{reverse("settlement_cost_rule_list")}?{query}')
        self.assertContains(listing, "T286 成本備註")
        programs = self.client.get(f'{reverse("dealer_sales_program_list")}?{query}')
        self.assertContains(programs, f'id="program-{self.model.pk}"')

    def test_inactive_model_links_to_inactive_program_tab(self):
        VehicleModel.objects.filter(pk=self.model.pk).update(active=False)
        commission = self.client.get(self.url("vehicle_model_commission"))
        self.assertContains(commission,
                            f'{reverse("dealer_sales_program_list")}?q=T286DA&amp;status=inactive#program-{self.model.pk}')

    def test_direct_posts_to_the_three_tabs_are_rejected(self):
        commission = self.client.post(self.url("vehicle_model_commission"),
                                      {"action": "save_commission", "base_dealer_commission": "9999"})
        self.assertEqual(commission.status_code, 405)
        cost_payload = {"action": "save", "amount": "1", "announced_on": "2026-09-01",
                        "effective_from": "2026-09-01", "active": "on"}
        self.assertEqual(self.client.post(self.url("vehicle_model_settlement_costs"), cost_payload).status_code, 405)
        self.assertEqual(self.client.post(self.url("vehicle_model_settlement_costs"),
                                          {"action": "delete", "rule_id": self.rule.pk}).status_code, 405)
        self.assertEqual(self.client.post(self.url("vehicle_model_incentives"), {"action": "save"}).status_code, 405)
        self.model.refresh_from_db()
        self.assertEqual(self.model.base_dealer_commission, Decimal("1500"))
        self.assertEqual(list(VehicleSettlementCostRule.objects.values_list("pk", "amount")),
                         [(self.rule.pk, Decimal("56000"))])

    def test_shared_quick_toggle_still_works_from_dedicated_cost_page(self):
        listing = self.client.get(reverse("settlement_cost_rule_list"))
        self.assertContains(listing, reverse("master_record_set_active", args=["settlement-cost-rule", self.rule.pk]))
        response = self.client.post(reverse("master_record_set_active", args=["settlement-cost-rule", self.rule.pk]),
                                    {"active": "0"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        self.rule.refresh_from_db()
        self.assertFalse(self.rule.active)

    def test_other_tabs_keep_their_forms(self):
        for name in ("vehicle_model_edit", "vehicle_model_price_versions", "vehicle_installment_plan_list"):
            with self.subTest(tab=name):
                url = reverse(name, args=[self.model.pk])
                params = {"new": 1} if name != "vehicle_model_edit" else {}
                main = self.client.get(url, params).content.decode().split('<main', 1)[1]
                self.assertIsNotNone(POST_FORM.search(main))


class ProgramListCommissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.model = VehicleModel.objects.create(
            brand="SUZUKI", name="T286 傭金車", model_number="T286CM", model_year=2026,
            energy_type=VehicleModel.EnergyType.GAS, displacement_cc=125, base_dealer_commission=Decimal("1500"),
        )
        cls.other = VehicleModel.objects.create(
            brand="SYM", name="T286 其他車", model_number="T286OT", model_year=2026,
            energy_type=VehicleModel.EnergyType.GAS, displacement_cc=125, base_dealer_commission=Decimal("800"),
        )
        cls.url = reverse("dealer_sales_program_list")

    def user(self, name, **screens):
        user = get_user_model().objects.create_user(name, password="Test-Only-123")
        UserAccessState.objects.create(user=user, configured=True)
        for key, operate in screens.items():
            ScreenAccessGrant.objects.create(user=user, screen_key=key, view=True, operate=operate)
        self.client.force_login(user)
        return user

    def save(self, value, model=None, **extra):
        return self.client.post(self.url, {"vehicle_model": (model or self.model).pk,
                                           "base_dealer_commission": value, **extra})

    def test_commissions_only_operator_edits_on_the_page(self):
        self.user("t286-commissions", commissions=True)
        page = self.client.get(self.url)
        self.assertContains(page, f'id="commission-form-{self.model.pk}"')
        self.assertContains(page, f'form="commission-form-{self.model.pk}" value="1500"')
        self.assertContains(page, "套用基礎傭金")
        self.assertNotContains(page, reverse("vehicle_model_commission", args=[self.model.pk]))
        # 沒有機種權限也能設定；只改這一台，其他車型不動。
        self.assertEqual(self.client.get(reverse("vehicle_model_list")).status_code, 403)
        response = self.save("1800")
        self.assertRedirects(response, f"{self.url}#program-{self.model.pk}", fetch_redirect_response=False)
        self.model.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual((self.model.base_dealer_commission, self.other.base_dealer_commission),
                         (Decimal("1800"), Decimal("800")))

    def test_save_returns_to_same_filters_and_row(self):
        self.user("t286-filters", commissions=True)
        response = self.save("1200", return_query="q=T286&brand=SUZUKI&page=2&evil=1")
        self.assertRedirects(response, f"{self.url}?q=T286&brand=SUZUKI&page=2#program-{self.model.pk}",
                             fetch_redirect_response=False)
        page = self.client.get(self.url, {"q": "T286", "brand": "SUZUKI"})
        self.assertContains(page, 'name="return_query" value="q=T286&amp;brand=SUZUKI"')

    def test_invalid_amount_is_not_saved(self):
        self.user("t286-invalid", commissions=True)
        for value in ("-1", "abc", "", "12.5"):
            with self.subTest(value=value):
                response = self.client.get(self.save(value)["Location"])
                self.assertContains(response, "車行基礎傭金未更新")
        self.model.refresh_from_db()
        self.assertEqual(self.model.base_dealer_commission, Decimal("1500"))
        self.assertEqual(self.client.post(self.url, {"vehicle_model": "999999", "base_dealer_commission": "1"}).status_code,
                         404)
        self.assertEqual(self.client.post(self.url, {"vehicle_model": "x", "base_dealer_commission": "1"}).status_code,
                         404)

    def test_view_only_user_sees_amount_but_cannot_save(self):
        self.user("t286-viewer", commissions=False)
        page = self.client.get(self.url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "$1500")
        self.assertNotContains(page, 'name="base_dealer_commission"')
        self.assertNotContains(page, "套用基礎傭金")
        self.assertEqual(self.save("1800").status_code, 403)
        self.model.refresh_from_db()
        self.assertEqual(self.model.base_dealer_commission, Decimal("1500"))

    def test_user_without_commissions_cannot_open_or_save(self):
        self.user("t286-models", models=True)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.save("1800").status_code, 403)
        self.model.refresh_from_db()
        self.assertEqual(self.model.base_dealer_commission, Decimal("1500"))


class DedicatedCostPageTests(TestCase):
    """工作區結算成本的寫入測試刪除後，同樣的規則改在「車輛結算成本」專屬頁驗證。"""

    @classmethod
    def setUpTestData(cls):
        cls.root = get_user_model().objects.create_superuser("t286-cost-root", password="Test-Only-123")
        cls.model = VehicleModel.objects.create(
            brand="SUZUKI", name="T286 成本車", model_number="T286CO", model_year=2026,
            energy_type=VehicleModel.EnergyType.GAS, displacement_cc=125)
        cls.other = VehicleModel.objects.create(
            brand="SYM", name="T286 另一台", model_number="T286OB", model_year=2026,
            energy_type=VehicleModel.EnergyType.GAS, displacement_cc=150)
        cls.inactive = VehicleModel.objects.create(
            brand="AEON", name="T286 停用車", model_number="T286IN", model_year=2024,
            energy_type=VehicleModel.EnergyType.GAS, displacement_cc=125, active=False)
        cls.list_url = reverse("settlement_cost_rule_list")

    def setUp(self):
        self.client.force_login(self.root)

    def payload(self, model, **extra):
        return {"vehicle_model": model.pk, "amount": "52000", "announced_on": "2026-09-01",
                "effective_from": "2026-09-01", "effective_to": "", "note": "", "active": "on", **extra}

    def test_create_uses_the_model_selected_in_form(self):
        response = self.client.post(reverse("settlement_cost_rule_create"), self.payload(self.other))
        self.assertRedirects(response, self.list_url, fetch_redirect_response=False)
        rule = VehicleSettlementCostRule.objects.get()
        self.assertEqual((rule.vehicle_model, rule.amount), (self.other, Decimal("52000")))
        self.assertContains(self.client.get(self.list_url), "$52000")

    def test_edit_and_delete_return_to_list(self):
        rule = VehicleSettlementCostRule.objects.create(vehicle_model=self.model, amount=50000,
                                                        effective_from=date(2026, 1, 1))
        kept = VehicleSettlementCostRule.objects.create(vehicle_model=self.other, amount=1,
                                                        effective_from=date(2026, 1, 1))
        self.assertEqual(self.client.get(reverse("settlement_cost_rule_edit", args=[999999])).status_code, 404)
        response = self.client.post(reverse("settlement_cost_rule_edit", args=[rule.pk]),
                                    self.payload(self.model, amount="51000", effective_from="2026-01-01"))
        self.assertRedirects(response, self.list_url, fetch_redirect_response=False)
        rule.refresh_from_db()
        self.assertEqual((rule.amount, rule.vehicle_model_id), (Decimal("51000"), self.model.pk))

        self.assertEqual(self.client.post(reverse("settlement_cost_rule_delete", args=[999999])).status_code, 404)
        response = self.client.post(reverse("settlement_cost_rule_delete", args=[rule.pk]))
        self.assertRedirects(response, self.list_url, fetch_redirect_response=False)
        self.assertFalse(VehicleSettlementCostRule.objects.filter(pk=rule.pk).exists())
        self.assertTrue(VehicleSettlementCostRule.objects.filter(pk=kept.pk).exists())

    def test_duplicate_start_date_is_a_form_error(self):
        VehicleSettlementCostRule.objects.create(vehicle_model=self.model, amount=1, effective_from=date(2026, 9, 1))
        response = self.client.post(reverse("settlement_cost_rule_create"), self.payload(self.model))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertEqual(VehicleSettlementCostRule.objects.count(), 1)

    def test_model_choices_list_inactive_models_last_and_marked(self):
        field = self.client.get(reverse("settlement_cost_rule_create")).context["form"].fields["vehicle_model"]
        choices = [(value.value, label) for value, label in field.choices if value]
        self.assertEqual([pk for pk, _label in choices][-1], self.inactive.pk)
        labels = dict(choices)
        self.assertEqual(labels[self.inactive.pk], "T286 停用車／T286IN／2024（停用）")
        self.assertNotIn("停用", labels[self.model.pk])
