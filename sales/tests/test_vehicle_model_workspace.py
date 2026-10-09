"""機種工作區：同一年式的各項設定集中在分頁，送出後一律回到同一分頁。"""
import re
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import (
    BrandRegistrationFeeRule,
    DealerVolumeBonusRule,
    InstallmentCompany,
    InstallmentPlanVersion,
    VehicleColor,
    VehicleIncentiveRule,
    VehicleModel,
    VehiclePriceVersion,
    VehicleSettlementCostRule,
)

TAB_ROUTES = {
    "規格與車色": ("vehicle_model_edit", "pk"),
    "售價": ("vehicle_model_price_versions", "model_pk"),
    "分期": ("vehicle_installment_plan_list", "model_pk"),
    "傭金與獎勵": ("vehicle_model_commission", "model_pk"),
    "結算成本": ("vehicle_model_settlement_costs", "model_pk"),
    "原廠獎勵與補助": ("vehicle_model_incentives", "model_pk"),
    "選車圖片與介紹": ("catalog_edit", "pk"),
    "適用規則": ("vehicle_model_rules", "model_pk"),
}


class VehicleModelWorkspaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.root = user_model.objects.create_superuser("admin", password="Test-Only-123")
        cls.manager = user_model.objects.create_superuser("manager", password="Test-Only-123")
        cls.limited = user_model.objects.create_user("models-only", password="Test-Only-123")
        UserAccessState.objects.create(user=cls.limited, configured=True)
        ScreenAccessGrant.objects.create(user=cls.limited, screen_key="models", view=True, operate=True)
        cls.model = VehicleModel.objects.create(
            brand="SUZUKI", name="工作區測試車", model_number="WS125", model_year=2026,
            model_code=VehicleModel.ModelType.CBS_DISC, energy_type=VehicleModel.EnergyType.GAS,
            displacement_cc=125,
        )
        VehicleColor.objects.create(vehicle_model=cls.model, name="白")
        cls.other = VehicleModel.objects.create(
            brand="SYM", name="另一台", model_number="OT150", model_year=2026,
            energy_type=VehicleModel.EnergyType.GAS, displacement_cc=150,
        )

    def setUp(self):
        self.client.force_login(self.root)

    def tab_url(self, label, model=None):
        route, kwarg = TAB_ROUTES[label]
        return reverse(route, kwargs={kwarg: (model or self.model).pk})

    def test_every_tab_renders_inside_one_workspace(self):
        for label in TAB_ROUTES:
            with self.subTest(tab=label):
                response = self.client.get(self.tab_url(label))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "data-model-workspace-tabs")
                self.assertContains(response, "<h1>工作區測試車</h1>", html=False)
                self.assertContains(response, f'href="{self.tab_url(label)}" aria-current="page"')
                for other in TAB_ROUTES:
                    self.assertContains(response, f'href="{self.tab_url(other)}"')
                self.assertContains(response, f'href="{reverse("vehicle_model_list")}"')
                self.assertNotContains(response, 'id="business-settings"')

    def test_list_marks_whether_the_current_suggested_price_includes_registration(self):
        VehiclePriceVersion.objects.create(
            vehicle_model=self.model, suggested_price=Decimal("65980"),
            suggested_price_includes_registration=True, effective_from=date(2026, 1, 1))
        VehiclePriceVersion.objects.create(
            vehicle_model=self.other, suggested_price=Decimal("59980"),
            suggested_price_includes_registration=False, effective_from=date(2026, 1, 1))
        self.client.force_login(self.root)
        html = self.client.get(reverse("vehicle_model_list")).content.decode()
        for model, price, label in ((self.model, "65,980", "含牌險"), (self.other, "59,980", "不含牌險")):
            row = re.search(rf'<tr[^>]*>(?:(?!</tr>).)*?{model.model_number}(?:(?!</tr>).)*?</tr>', html, re.S)
            self.assertIsNotNone(row, model.model_number)
            cell = re.search(r'data-label="目前建議售價">(.*?)</td>', row.group(0), re.S).group(1)
            self.assertIn(price.replace(",", ""), cell.replace(",", ""))
            self.assertIn(f'>{label}</span>', cell)
            self.assertNotIn("不含牌險" if label == "含牌險" else ">含牌險<", cell)

    def test_price_without_a_current_version_shows_not_set_and_no_scope_label(self):
        self.client.force_login(self.root)
        html = self.client.get(reverse("vehicle_model_list")).content.decode()
        self.assertIn("尚未設定", html)
        self.assertNotIn("price-scope--included", html)

    def navigator(self, response):
        return response.context["ws"]["navigator"] if "ws" in response.context else None

    def test_model_list_drawer_jumps_to_the_same_tab_of_another_model(self):
        response = self.client.get(self.tab_url("售價"))
        self.assertContains(response, "data-model-nav")
        html = response.content.decode()
        # 目前這台在清單裡被標示；另一台的連結指向它的「售價」分頁
        self.assertIn(f'href="{self.tab_url("售價")}" aria-current="page"', html)
        self.assertIn(f'href="{self.tab_url("售價", self.other)}"', html)
        self.assertNotIn(f'href="{self.tab_url("規格與車色", self.other)}"', html)
        self.assertContains(response, "點年式會停在「售價」分頁")

    def test_drawer_orders_parent_brand_first_then_sub_brands_by_name_and_inactive_last(self):
        from sales.models import VehicleBrand
        parent = VehicleBrand.objects.create(name="清單主牌", display_order=1)
        VehicleBrand.objects.create(name="清單子牌B", parent=parent, display_order=1)
        VehicleBrand.objects.create(name="清單子牌A", parent=parent, display_order=1)

        def make(brand, name, number, active=True, cc=125):
            return VehicleModel.objects.create(
                brand=brand, name=name, model_number=number, model_year=2026, active=active,
                model_code=VehicleModel.ModelType.DRUM, energy_type=VehicleModel.EnergyType.GAS, displacement_cc=cc)

        make("清單子牌B", "子B車", "LB1")
        make("清單子牌A", "子A車", "LA1")
        make("清單主牌", "主牌停用車", "LM0", active=False, cc=50)
        make("清單主牌", "主牌車", "LM1", cc=400)
        response = self.client.get(self.tab_url("售價"))
        group = next(g for g in self.navigator(response) if g["name"] == "清單主牌")
        order = [(section["label"], [family["name"] for family in section["families"]]) for section in group["sections"]]
        self.assertEqual(order, [("", ["主牌車"]), ("清單子牌A", ["子A車"]), ("清單子牌B", ["子B車"]),
                                 ("已停用", ["主牌停用車"])])  # 停用的統一放最後，與列表頁一致
        self.assertContains(response, "已停用")

    def test_tab_falls_back_when_target_cannot_use_it(self):
        inactive = VehicleModel.objects.create(
            brand="SUZUKI", name="停用測試車", model_number="IN125", model_year=2025, active=False,
            model_code=VehicleModel.ModelType.DRUM, energy_type=VehicleModel.EnergyType.GAS, displacement_cc=125)
        response = self.client.get(self.tab_url("選車圖片與介紹"))
        html = response.content.decode()
        # 停用機種不能編輯選車展示：改連到它的「規格與車色」
        self.assertIn(f'href="{self.tab_url("規格與車色", inactive)}"', html)
        self.assertIn(f'href="{self.tab_url("選車圖片與介紹", self.other)}"', html)

    def test_same_year_variants_show_their_type(self):
        twin = VehicleModel.objects.create(
            brand=self.model.brand, family=self.model.family, name=self.model.name, model_number="WS125B",
            model_year=self.model.model_year, model_code=VehicleModel.ModelType.DRUM,
            energy_type=VehicleModel.EnergyType.GAS, displacement_cc=125)
        response = self.client.get(self.tab_url("售價"))
        labels = [year["label"] for group in self.navigator(response) for section in group["sections"]
                  for family in section["families"] for year in family["years"]
                  if year["pk"] in (self.model.pk, twin.pk)]
        self.assertEqual(len(labels), 2)
        self.assertTrue(all(label.startswith("2026 ") for label in labels), labels)

    def test_limited_user_only_gets_links_to_tabs_they_can_open(self):
        self.client.force_login(self.limited)
        response = self.client.get(self.tab_url("售價"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(f'href="{self.tab_url("售價", self.other)}"', html)

    def test_tabs_follow_screen_permissions(self):
        catalog_url = self.tab_url("選車圖片與介紹")
        self.client.force_login(self.manager)
        response = self.client.get(self.tab_url("規格與車色"))
        self.assertNotContains(response, catalog_url)
        self.assertNotContains(response, "選車圖片與介紹")
        self.assertContains(response, self.tab_url("結算成本"))

        self.client.force_login(self.limited)
        response = self.client.get(self.tab_url("售價"))
        self.assertEqual(response.status_code, 200)
        for label in ("規格與車色", "售價", "分期", "適用規則"):
            self.assertContains(response, f'href="{self.tab_url(label)}"')
        for label in ("傭金與獎勵", "結算成本", "原廠獎勵與補助", "選車圖片與介紹"):
            self.assertNotContains(response, f'href="{self.tab_url(label)}"')
        self.assertEqual(self.client.get(self.tab_url("結算成本")).status_code, 403)
        rules = self.client.get(self.tab_url("適用規則"))
        self.assertContains(rules, "需要「領牌與強制險規則」權限")
        self.assertContains(rules, "需要「車行台數獎金與結算」權限")

    def test_inactive_model_disables_catalog_tab(self):
        self.model.active = False
        self.model.save()
        response = self.client.get(self.tab_url("規格與車色"))
        self.assertNotContains(response, f'href="{self.tab_url("選車圖片與介紹")}"')
        self.assertContains(response, "機種啟用後才能編輯選車展示")
        self.assertContains(response, "已停用")

    def test_create_page_only_offers_spec_tab(self):
        response = self.client.get(reverse("vehicle_model_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "新增機種／年式")
        self.assertContains(response, 'aria-disabled="true"', count=7)
        self.assertContains(response, "儲存後即可設定")
        self.assertIsNone(re.search(r"/data/vehicle-models/\d+/", response.content.decode()))

    def test_spec_save_returns_to_spec_tab(self):
        color = self.model.colors.get()
        response = self.client.post(self.tab_url("規格與車色"), {
            "action": "save_model", "brand": "SUZUKI", "energy_type": "gas", "name": "工作區測試車",
            "model_number": "WS125", "model_year": 2026, "model_code": VehicleModel.ModelType.CBS_DISC,
            "displacement_cc": 125, "active": "on",
            "colors-TOTAL_FORMS": "1", "colors-INITIAL_FORMS": "1", "colors-MIN_NUM_FORMS": "0",
            "colors-MAX_NUM_FORMS": "1000", "colors-0-id": color.pk, "colors-0-name": "白", "colors-0-active": "on",
        })
        self.assertRedirects(response, self.tab_url("規格與車色"), fetch_redirect_response=False)

    def cost_payload(self, **extra):
        return {"action": "save", "vehicle_model": self.other.pk, "amount": "52000", "announced_on": "2026-09-01",
                "effective_from": "2026-09-01", "effective_to": "", "note": "", "active": "on", **extra}

    def test_cost_tab_creates_for_this_model_even_if_post_names_another(self):
        url = self.tab_url("結算成本")
        response = self.client.post(url, self.cost_payload())
        self.assertRedirects(response, url, fetch_redirect_response=False)
        rule = VehicleSettlementCostRule.objects.get()
        self.assertEqual(rule.vehicle_model, self.model)
        self.assertEqual(rule.amount, Decimal("52000"))
        page = self.client.get(url)
        self.assertContains(page, "$52000")
        self.assertNotContains(page, 'name="vehicle_model"')

    def test_cost_tab_edit_and_delete_stay_in_tab(self):
        url = self.tab_url("結算成本")
        rule = VehicleSettlementCostRule.objects.create(
            vehicle_model=self.model, amount=50000, effective_from=date(2026, 1, 1))
        foreign = VehicleSettlementCostRule.objects.create(
            vehicle_model=self.other, amount=1, effective_from=date(2026, 1, 1))
        self.assertContains(self.client.get(url, {"edit": rule.pk}), "編輯 2026/01/01 版本")
        self.assertEqual(self.client.get(url, {"edit": foreign.pk}).status_code, 404)
        self.assertEqual(self.client.get(url, {"edit": "abc"}).status_code, 404)

        response = self.client.post(url, self.cost_payload(rule_id=rule.pk, amount="51000", effective_from="2026-01-01"))
        self.assertRedirects(response, url, fetch_redirect_response=False)
        rule.refresh_from_db()
        self.assertEqual((rule.amount, rule.vehicle_model_id), (Decimal("51000"), self.model.pk))

        self.assertEqual(self.client.post(url, {"action": "delete", "rule_id": foreign.pk}).status_code, 404)
        response = self.client.post(url, {"action": "delete", "rule_id": rule.pk})
        self.assertRedirects(response, url, fetch_redirect_response=False)
        self.assertFalse(VehicleSettlementCostRule.objects.filter(pk=rule.pk).exists())
        self.assertTrue(VehicleSettlementCostRule.objects.filter(pk=foreign.pk).exists())

    def test_cost_tab_reports_duplicate_start_date_as_form_error(self):
        VehicleSettlementCostRule.objects.create(vehicle_model=self.model, amount=1, effective_from=date(2026, 9, 1))
        response = self.client.post(self.tab_url("結算成本"), self.cost_payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(VehicleSettlementCostRule.objects.count(), 1)
        self.assertTrue(response.context["form"].errors)

    def test_incentive_tab_forces_model_and_keeps_platform_help(self):
        url = self.tab_url("原廠獎勵與補助")
        page = self.client.get(url)
        self.assertContains(page, "僅網路平台來源的訂單會自動帶入")
        response = self.client.post(url, {
            "action": "save", "vehicle_model": self.other.pk, "sales_bonus": "1000", "promotion_subsidy": "500",
            "installment_interest_subsidy": "0", "announced_on": "2026-09-01", "effective_from": "2026-09-01",
            "effective_to": "", "note": "", "active": "on",
        })
        self.assertRedirects(response, url, fetch_redirect_response=False)
        rule = VehicleIncentiveRule.objects.get()
        self.assertEqual(rule.vehicle_model, self.model)
        response = self.client.post(url, {"action": "delete", "rule_id": rule.pk})
        self.assertRedirects(response, url, fetch_redirect_response=False)
        self.assertFalse(VehicleIncentiveRule.objects.exists())

    def test_inactive_model_can_still_receive_cost_versions(self):
        self.model.active = False
        self.model.save()
        url = self.tab_url("結算成本")
        self.assertRedirects(self.client.post(url, self.cost_payload()), url, fetch_redirect_response=False)
        self.assertEqual(VehicleSettlementCostRule.objects.get().vehicle_model, self.model)

    def test_existing_tab_posts_return_to_their_tab(self):
        price_url = self.tab_url("售價")
        response = self.client.post(price_url, {
            "action": "save", "suggested_price": "88000", "cash_price": "", "announced_on": "2026-09-01",
            "effective_from": "2026-09-01", "effective_to": "", "source_note": "", "active": "on",
        })
        self.assertRedirects(response, price_url, fetch_redirect_response=False)
        self.assertTrue(VehiclePriceVersion.objects.filter(vehicle_model=self.model).exists())

        commission_url = self.tab_url("傭金與獎勵")
        response = self.client.post(commission_url, {"action": "save_commission", "base_dealer_commission": "1200"})
        self.assertEqual(response["Location"], f"{commission_url}#cash-commission")
        response = self.client.post(commission_url, {"action": "save_commission", "base_dealer_commission": "1300",
                                                     "from": "programs"})
        self.assertEqual(response["Location"], f"{commission_url}?from=programs#cash-commission")
        back = self.client.get(commission_url, {"from": "programs"})
        self.assertContains(back, f'href="{reverse("dealer_sales_program_list")}"')
        self.assertContains(back, "回到車行傭金與銷售獎勵")
        self.assertContains(self.client.get(commission_url), "回到機種與售價")

        company = InstallmentCompany.objects.create(name="工作區分期")
        installment_url = self.tab_url("分期")
        response = self.client.post(installment_url, {
            "plan-announced_on": "2026-08-10", "plan-effective_from": "2026-09-01", "plan-effective_to": "",
            "plan-note": "", "plan-active": "on",
            "options-TOTAL_FORMS": "1", "options-INITIAL_FORMS": "0", "options-MIN_NUM_FORMS": "0",
            "options-MAX_NUM_FORMS": "1000", "options-0-periods": "24", "options-0-monthly_amount": "3000",
            "options-0-company": str(company.pk), "options-0-opening_fee": "0",
            "options-0-expected_disbursement_method": "fixed", "options-0-expected_disbursement_rate": "",
            "options-0-expected_disbursement_fixed_amount": "60000", "options-0-extra_disbursement_bonus": "0",
        })
        plan = InstallmentPlanVersion.objects.get(vehicle_model=self.model)
        self.assertTrue(response["Location"].startswith(f"{installment_url}?edit={plan.pk}"))

        catalog_url = self.tab_url("選車圖片與介紹")
        response = self.client.post(catalog_url, {"expected_revision": 0, "description": "介紹", "position": 0})
        self.assertRedirects(response, catalog_url, fetch_redirect_response=False)

    def test_program_list_enters_commission_tab_with_return_path(self):
        response = self.client.get(reverse("dealer_sales_program_list"))
        self.assertContains(response, f'{self.tab_url("傭金與獎勵")}?from=programs')

    def test_rules_tab_lists_only_rules_that_apply_to_this_model(self):
        BrandRegistrationFeeRule.objects.create(
            brand="SUZUKI", energy_type="gas", calculation_type="fixed_bundle", fixed_total=1800,
            min_cc=101, max_cc=150, insurance_period_years=1, effective_from=date(2020, 1, 1), note="適用本車")
        BrandRegistrationFeeRule.objects.create(
            brand="SUZUKI", energy_type="gas", calculation_type="fixed_bundle", fixed_total=9999,
            min_cc=151, max_cc=250, insurance_period_years=1, effective_from=date(2020, 1, 1))
        BrandRegistrationFeeRule.objects.create(
            brand="SYM", energy_type="gas", calculation_type="fixed_bundle", fixed_total=7777,
            insurance_period_years=1, effective_from=date(2020, 1, 1))
        matching = DealerVolumeBonusRule.objects.create(
            name="鈴木季獎", brand="SUZUKI", starts_on=date(2026, 1, 1), ends_on=date(2026, 12, 31))
        DealerVolumeBonusRule.objects.create(
            name="三陽季獎", brand="SYM", starts_on=date(2026, 1, 1), ends_on=date(2026, 12, 31))
        targeted = DealerVolumeBonusRule.objects.create(
            name="指定別台", starts_on=date(2026, 1, 1), ends_on=date(2026, 12, 31))
        targeted.vehicle_models.add(self.other)

        response = self.client.get(self.tab_url("適用規則"))
        self.assertContains(response, "$1,800")
        self.assertContains(response, "今天套用")
        self.assertNotContains(response, "9,999")
        self.assertNotContains(response, "7,777")
        self.assertContains(response, matching.display_name)
        self.assertNotContains(response, "三陽季獎")
        self.assertNotContains(response, "指定別台")
        self.assertContains(response, reverse("brand_registration_fee_rule_list"))
        self.assertContains(response, reverse("dealer_volume_bonus_list"))

    def test_rules_tab_asks_for_displacement_before_matching_gas_rules(self):
        self.model.displacement_cc = None
        self.model.save(update_fields=["displacement_cc"])
        response = self.client.get(self.tab_url("適用規則"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "請先補上排氣量")

    def test_global_rule_pages_keep_working(self):
        response = self.client.post(reverse("settlement_cost_rule_create"), {
            "vehicle_model": self.model.pk, "amount": "1000", "announced_on": "2026-09-01",
            "effective_from": "2026-09-01", "effective_to": "", "note": "", "active": "on",
        })
        self.assertRedirects(response, reverse("settlement_cost_rule_list"), fetch_redirect_response=False)
        rule = VehicleSettlementCostRule.objects.get()
        response = self.client.post(reverse("settlement_cost_rule_delete", args=[rule.pk]))
        self.assertRedirects(response, reverse("settlement_cost_rule_list"), fetch_redirect_response=False)
        self.assertFalse(VehicleSettlementCostRule.objects.exists())
        self.assertEqual(self.client.get(reverse("incentive_rule_create")).status_code, 200)

    def test_tab_status_shows_set_or_unset_instead_of_counts(self):
        VehicleModel.objects.filter(pk=self.model.pk).update(base_dealer_commission=2000)
        page = self.client.get(reverse("vehicle_model_commission", args=[self.model.pk])).content.decode()
        # 基礎傭金有值、沒有附加獎勵時，傭金分頁仍算已設定。
        self.assertIn("基礎傭金 2,000 元；附加獎勵 0 個版本", page)
        self.assertIn("（已設定：基礎傭金 2,000 元；附加獎勵 0 個版本）", page)
        self.assertIn("（未設定：0 個獎勵版本）", page)
        self.assertNotIn("筆版本）", page)

    def test_model_list_shows_commission_and_current_rewards(self):
        from datetime import timedelta

        from django.utils import timezone

        from sales.models import DealerRewardCatalogItem, DealerVehicleRewardItem, DealerVehicleRewardPlan

        VehicleModel.objects.filter(pk=self.model.pk).update(base_dealer_commission=2000)
        voucher = DealerRewardCatalogItem.objects.create(reward_type="voucher", name="郵政禮券", unit="元")
        today = timezone.localdate()
        plan = DealerVehicleRewardPlan.objects.create(vehicle_model=self.model, effective_from=today,
                                                      effective_to=today + timedelta(days=30), active=True)
        DealerVehicleRewardItem.objects.create(plan=plan, catalog_item=voucher, reward_type="voucher",
                                               name="郵政禮券", quantity=10000, unit="元")
        page = self.client.get(reverse("vehicle_model_list")).content.decode()
        self.assertIn("傭金與附加獎勵", page)
        self.assertIn("傭金 $2,000", page)
        self.assertIn("郵政禮券 10,000元", page)
