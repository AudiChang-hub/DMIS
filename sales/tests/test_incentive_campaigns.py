"""T-149（使用者 2026-11-11 選 A）：原廠獎勵與補助、車行附加獎勵改為活動制。

- 活動條件：品牌、能源別、指定年式（多選）、期間；原廠活動另有適用通路與促銷補助通路，車行活動另有適用車行。
- 原廠：常態取開始日最新的一筆＋加碼累加；依實際領牌日；領牌完成固定；改領牌日重算、人工值保留（T-147）。
- 車行：符合的活動全部累加；依實際領牌日存訂單明細；只給有收款車行的訂單；改領牌日重新套用。
- 既有車型版本一對一轉成活動，轉換前後每個年式的結果相同。
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.test import TestCase
from django.urls import reverse

from sales.models import (
    DealerRewardCampaign,
    DealerRewardCampaignItem,
    DealerRewardCatalogItem,
    DealerRewardCostVersion,
    DealerVehicleRewardItem,
    DealerVehicleRewardPlan,
    IncentiveCampaign,
    OrderDealerRewardLine,
    OrderIncentiveApplication,
    OrderOperationsProfile,
    SalesOrder,
    SalesSource,
    Store,
    VehicleColor,
    VehicleIncentiveRule,
    VehicleInventory,
    VehicleModel,
    VehicleSettlementCostRule,
)
from sales.services.dealer_reward_campaign import apply_order_dealer_rewards
from sales.services.incentive_rule import apply_order_incentive_rule, incentive_totals
from sales.signals import _refresh_campaign_orders
from sales.tests.campaign_helpers import convert_legacy_versions

GAS = VehicleModel.EnergyType.GAS
ELECTRIC = VehicleModel.EnergyType.ELECTRIC
LIGHT = VehicleModel.EnergyType.LIGHT_ELECTRIC
MICRO = VehicleModel.EnergyType.MICRO_ELECTRIC


def _old_resolve(model_id, day):
    """T-149 前的車型版本解析（incentive_rule.resolve_incentive_rule 原樣），用來比對轉換前後結果。"""
    return (
        VehicleIncentiveRule.objects.filter(vehicle_model_id=model_id, active=True, effective_from__lte=day)
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=day))
        .order_by("-effective_from", "-id").first()
    )


def _old_amounts(rule, source_type):
    if rule is None:
        return {"sales_bonus": 0, "promotion_subsidy": 0, "installment_interest_subsidy": 0}
    return {
        "sales_bonus": rule.sales_bonus,
        "promotion_subsidy": rule.promotion_subsidy if source_type == "platform" else 0,
        "installment_interest_subsidy": rule.installment_interest_subsidy,
    }


class CampaignFixtureMixin:
    def make_model(self, brand, name, energy, year=2026):
        return VehicleModel.objects.create(brand=brand, name=name, energy_type=energy, model_year=year,
                                           displacement_cc=125 if energy == GAS else None)

    def make_order(self, vehicle_model, *, source=None, source_type=SalesOrder.SourceType.STORE, registration_date=None):
        from sales.services.print_company import initialize_company

        color = VehicleColor.objects.get_or_create(vehicle_model=vehicle_model, name="灰")[0]
        if source is None and source_type == SalesOrder.SourceType.PLATFORM:
            source = SalesSource.objects.get_or_create(name="測試平台", source_type="platform")[0]
        order = SalesOrder(
            owner_name="測試車主", owner_phone="0900000000", owner_address="測試地址", owner_id_number="A100000001",
            vehicle_model=vehicle_model, color=color, vehicle_price=Decimal("75000"), deposit_amount=Decimal("5000"),
            actual_balance=Decimal("70000"), id_verified=True, status=SalesOrder.Status.ALLOCATION_PENDING,
            source=source, source_type=source_type,
        )
        initialize_company(order, self.admin)
        order.save()
        if registration_date:
            SalesOrder.objects.filter(pk=order.pk).update(registration_date=registration_date)
            order.refresh_from_db()
        return order


class LegacyConversionTests(CampaignFixtureMixin, TestCase):
    """轉換前後比對：每個年式、每個日期、每種來源的三項金額完全相同。"""

    def test_conversion_keeps_every_model_result(self):
        models = [
            self.make_model("SUZUKI", "SUI 125", GAS),
            self.make_model("SUZUKI", "Gixxer 250", GAS, 2023),
            self.make_model("GOGORO", "VIVAMIX", ELECTRIC, 2024),
            self.make_model("eReady", "Fun", ELECTRIC, 2023),
            self.make_model("eMOVING", "EZ1", LIGHT, 2021),
            self.make_model("SUZUKI", "沒有版本", GAS),
        ]
        sui, gixxer, vivamix, fun, ez1, _none = models
        VehicleIncentiveRule.objects.create(vehicle_model=sui, sales_bonus=2000, promotion_subsidy=1500,
                                            effective_from=date(2026, 10, 1))
        VehicleIncentiveRule.objects.create(vehicle_model=sui, sales_bonus=1800, promotion_subsidy=1000,
                                            effective_from=date(2026, 8, 1))
        VehicleIncentiveRule.objects.create(vehicle_model=gixxer, sales_bonus=5000, promotion_subsidy=5000,
                                            installment_interest_subsidy=6600, effective_from=date(2026, 10, 1))
        VehicleIncentiveRule.objects.create(vehicle_model=vivamix, sales_bonus=1000, promotion_subsidy=1500,
                                            effective_from=date(2026, 10, 1), effective_to=date(2026, 10, 31))
        VehicleIncentiveRule.objects.create(vehicle_model=fun, sales_bonus=2000, promotion_subsidy=1500,
                                            effective_from=date(2026, 8, 1), active=False)
        VehicleIncentiveRule.objects.create(vehicle_model=ez1, sales_bonus=5000, effective_from=date(2026, 10, 1))
        days = [date(2026, 7, 31), date(2026, 8, 15), date(2026, 10, 1), date(2026, 10, 31), date(2026, 11, 11)]
        before = {
            (model.pk, day, source): _old_amounts(_old_resolve(model.pk, day), source)
            for model in models for day in days for source in ("platform", "dealer", "store")
        }

        convert_legacy_versions()
        convert_legacy_versions()  # 重跑不重複建立

        self.assertEqual(IncentiveCampaign.objects.count(), VehicleIncentiveRule.objects.count())
        for (model_id, day, source), expected in before.items():
            model = VehicleModel.objects.get(pk=model_id)
            _rows, totals, _matched, _promo, _regular = incentive_totals(model, source, day)
            self.assertEqual({key: Decimal(value) for key, value in expected.items()}, totals,
                             f"{model} {day} {source}")
        campaign = IncentiveCampaign.objects.get(legacy_rule__vehicle_model=gixxer)
        self.assertEqual((campaign.kind, campaign.promotion_source_types, campaign.source_types),
                         ("regular", ["platform"], []))
        self.assertEqual(list(campaign.vehicle_models.all()), [gixxer])

    def test_reward_plans_convert_to_all_dealer_campaigns_with_items(self):
        model = self.make_model("SUZUKI", "Gixxer SF 250", GAS, 2024)
        voucher = DealerRewardCatalogItem.objects.create(reward_type="voucher", name="郵政禮券", unit="元")
        plan = DealerVehicleRewardPlan.objects.create(vehicle_model=model, effective_from=date(2026, 10, 7))
        DealerVehicleRewardItem.objects.create(plan=plan, catalog_item=voucher, reward_type="voucher", name="郵政禮券",
                                               quantity=10000, unit="元", unit_cost_snapshot=1,
                                               cost_effective_on_snapshot=date(2026, 10, 7))

        convert_legacy_versions()

        campaign = DealerRewardCampaign.objects.get(legacy_plan=plan)
        self.assertEqual(list(campaign.vehicle_models.all()), [model])
        self.assertFalse(campaign.dealers.exists(), "轉換後為全部車行")
        item = campaign.items.get()
        self.assertEqual((item.catalog_item, item.quantity, item.unit_cost_snapshot), (voucher, 10000, 1))
        self.assertEqual(campaign.reward_summary, "郵政禮券 10000 元")


class IncentiveCampaignApplyTests(CampaignFixtureMixin, TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", "", "test-pass-123")
        self.client.force_login(self.admin)
        self.fun = self.make_model("eReady", "Fun", ELECTRIC, 2023)
        self.sui = self.make_model("SUZUKI", "SUI 125", GAS)
        self.regular = IncentiveCampaign.objects.create(
            name="Fun 原廠獎勵", sales_bonus=2000, promotion_subsidy=1500, effective_from=date(2026, 8, 1),
        )
        self.regular.vehicle_models.set([self.fun])
        self.bonus = IncentiveCampaign.objects.create(
            name="11 月特簽加碼", kind=IncentiveCampaign.Kind.BONUS, promotion_subsidy=500,
            energy_types=[ELECTRIC, LIGHT, MICRO], promotion_source_types=[],
            effective_from=date(2026, 11, 1), effective_to=date(2026, 11, 30),
        )

    def test_regular_plus_bonus_are_added_and_breakdown_is_saved(self):
        order = self.make_order(self.fun, source_type=SalesOrder.SourceType.PLATFORM, registration_date=date(2026, 11, 15))
        profile = apply_order_incentive_rule(order)
        self.assertEqual((profile.sales_bonus, profile.promotion_subsidy), (Decimal("2000"), Decimal("2000")))
        names = list(profile.incentive_applications.values_list("campaign_name", "kind", "promotion_subsidy"))
        self.assertEqual(names, [("Fun 原廠獎勵", "regular", Decimal("1500")), ("11 月特簽加碼", "bonus", Decimal("500"))])

    def test_promotion_channels_follow_each_campaign(self):
        store_order = self.make_order(self.fun, registration_date=date(2026, 11, 15))
        profile = apply_order_incentive_rule(store_order)
        # 常態促銷只給網路平台；加碼勾了全部通路，所以本店單也拿到 500。
        self.assertEqual((profile.sales_bonus, profile.promotion_subsidy), (Decimal("2000"), Decimal("500")))

    def test_bonus_ends_with_period_and_does_not_match_gas(self):
        order = self.make_order(self.fun, source_type=SalesOrder.SourceType.PLATFORM, registration_date=date(2026, 12, 1))
        self.assertEqual(apply_order_incentive_rule(order).promotion_subsidy, Decimal("1500"))
        gas_order = self.make_order(self.sui, source_type=SalesOrder.SourceType.PLATFORM,
                                    registration_date=date(2026, 11, 15))
        profile = apply_order_incentive_rule(gas_order)
        self.assertEqual((profile.sales_bonus, profile.promotion_subsidy), (Decimal("0"), Decimal("0")))
        self.assertFalse(profile.incentive_applications.exists())

    def test_newest_regular_replaces_older_and_source_types_limit_campaign(self):
        newer = IncentiveCampaign.objects.create(name="SUZUKI 品牌常態", brands=["suzuki"], sales_bonus=3000,
                                                 effective_from=date(2026, 10, 1), source_types=["dealer"])
        dealer = SalesSource.objects.create(name="甲車行", source_type="dealer")
        dealer_order = self.make_order(self.sui, source=dealer, source_type=SalesOrder.SourceType.DEALER,
                                       registration_date=date(2026, 11, 15))
        self.assertEqual(apply_order_incentive_rule(dealer_order).sales_bonus, Decimal("3000"))
        store_order = self.make_order(self.sui, registration_date=date(2026, 11, 15))
        self.assertEqual(apply_order_incentive_rule(store_order).sales_bonus, Decimal("0"), "只限車行通路")
        older = IncentiveCampaign.objects.create(name="SUI 舊常態", sales_bonus=1000, effective_from=date(2026, 9, 1))
        older.vehicle_models.set([self.sui])
        self.assertEqual(apply_order_incentive_rule(dealer_order).sales_bonus, Decimal("3000"), "開始日較新的常態優先")
        newer.active = False
        newer.save()
        self.assertEqual(apply_order_incentive_rule(dealer_order).sales_bonus, Decimal("1000"))

    def test_campaign_left_without_conditions_matches_nothing(self):
        """唯一指定的年式被刪除後，活動沒有任何車輛條件：不可變成全部車輛都適用。"""
        orphan = IncentiveCampaign.objects.create(name="孤兒活動", sales_bonus=9999, effective_from=date(2026, 1, 1))
        order = self.make_order(self.sui, source_type=SalesOrder.SourceType.PLATFORM, registration_date=date(2026, 11, 15))
        self.assertEqual(apply_order_incentive_rule(order).sales_bonus, Decimal("0"))
        self.assertFalse(OrderIncentiveApplication.objects.filter(campaign=orphan).exists())

    def test_manual_value_equal_to_total_returns_to_system(self):
        order = self.make_order(self.fun, source_type=SalesOrder.SourceType.PLATFORM, registration_date=date(2026, 11, 15))
        profile, _ = OrderOperationsProfile.objects.get_or_create(order=order)
        profile.promotion_subsidy = Decimal("2000")
        profile.sales_bonus = Decimal("999")
        profile.manual_financial_fields = ["promotion_subsidy", "sales_bonus"]
        profile.save()
        profile = apply_order_incentive_rule(order)
        self.assertEqual(profile.manual_financial_fields, ["sales_bonus"])
        self.assertEqual((profile.sales_bonus, profile.promotion_subsidy), (Decimal("999"), Decimal("2000")))

    def test_locked_order_is_not_changed_by_campaign_edits(self):
        order = self.make_order(self.fun, source_type=SalesOrder.SourceType.PLATFORM, registration_date=date(2026, 11, 15))
        apply_order_incentive_rule(order, "tester", lock=True)
        self.bonus.promotion_subsidy = 900
        self.bonus.save()
        _refresh_campaign_orders()
        profile = apply_order_incentive_rule(order)
        self.assertEqual(profile.promotion_subsidy, Decimal("2000"))

    def test_pending_orders_refresh_after_campaign_change(self):
        order = self.make_order(self.fun, source_type=SalesOrder.SourceType.PLATFORM, registration_date=date(2026, 11, 15))
        apply_order_incentive_rule(order)
        with self.captureOnCommitCallbacks(execute=True):
            self.bonus.promotion_subsidy = 800
            self.bonus.save()
        self.assertEqual(OrderOperationsProfile.objects.get(order=order).promotion_subsidy, Decimal("2300"))

    def test_used_campaign_cannot_be_deleted(self):
        order = self.make_order(self.fun, source_type=SalesOrder.SourceType.PLATFORM, registration_date=date(2026, 11, 15))
        apply_order_incentive_rule(order)
        response = self.client.post(reverse("incentive_campaign_delete", args=[self.bonus.pk]))
        self.assertRedirects(response, reverse("incentive_campaign_edit", args=[self.bonus.pk]))
        self.assertTrue(IncentiveCampaign.objects.filter(pk=self.bonus.pk).exists())
        self.assertTrue(OrderIncentiveApplication.objects.filter(campaign=self.bonus).exists())

    def campaign_post(self, **overrides):
        data = {
            "name": "測試活動", "kind": "bonus", "sales_bonus": "0", "promotion_subsidy": "500",
            "installment_interest_subsidy": "0", "promotion_source_types": ["platform", "store", "dealer"],
            "energy_types": [ELECTRIC], "announced_on": "2026-11-01", "effective_from": "2026-11-01",
            "effective_to": "2026-11-30", "active": "on", "note": "",
        }
        data.update(overrides)
        return self.client.post(reverse("incentive_campaign_create"), data)

    def test_form_creates_campaign_and_rejects_bad_conditions(self):
        response = self.campaign_post()
        self.assertRedirects(response, reverse("incentive_rule_list"))
        campaign = IncentiveCampaign.objects.get(name="測試活動")
        self.assertEqual((campaign.energy_types, campaign.kind), ([ELECTRIC], "bonus"))

        no_condition = self.campaign_post(name="沒有條件", energy_types=[])
        self.assertContains(no_condition, "請至少選擇一個品牌、能源別或指定年式")
        disjoint = self.campaign_post(name="沒有交集", brands=["SUZUKI"], energy_types=[ELECTRIC])
        self.assertContains(disjoint, "沒有任何年式符合")
        no_end = self.campaign_post(name="加碼沒結束日", effective_to="")
        self.assertContains(no_end, "加碼活動請填結束日期")
        self.assertFalse(IncentiveCampaign.objects.filter(name__in=["沒有條件", "沒有交集", "加碼沒結束日"]).exists())

    def test_same_day_regular_covering_same_model_is_rejected(self):
        response = self.campaign_post(name="重複常態", kind="regular", effective_from="2026-08-01", effective_to="",
                                      energy_types=[], vehicle_models=[self.fun.pk])
        self.assertContains(response, "已有同一天開始、涵蓋相同年式的常態活動：Fun 原廠獎勵")

    def test_list_workspace_and_order_page_show_campaigns(self):
        listing = self.client.get(reverse("incentive_rule_list"))
        self.assertContains(listing, "11 月特簽加碼")
        self.assertContains(listing, "加碼")
        tab = self.client.get(reverse("vehicle_model_incentives", args=[self.fun.pk]))
        self.assertContains(tab, "Fun 原廠獎勵")
        self.assertContains(tab, "11 月特簽加碼")
        self.assertNotContains(self.client.get(reverse("vehicle_model_incentives", args=[self.sui.pk])), "Fun 原廠獎勵")


class RegistrationFlowTests(CampaignFixtureMixin, TestCase):
    """經由領牌存檔：填好即完成並固定；改領牌日依新日期重新套用，人工值保留（T-147）。"""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", "", "test-pass-123")
        self.client.force_login(self.admin)
        self.model = self.make_model("SUZUKI", "Saluto 125", GAS)
        VehicleSettlementCostRule.objects.create(vehicle_model=self.model, amount=Decimal("60000"),
                                                 effective_from=date(2026, 1, 1))
        IncentiveCampaign.objects.create(name="SUZUKI 常態", brands=["SUZUKI"], sales_bonus=2000,
                                                   effective_from=date(2026, 1, 1))
        self.november = IncentiveCampaign.objects.create(
            name="11 月油車加碼", kind=IncentiveCampaign.Kind.BONUS, energy_types=[GAS], sales_bonus=500,
            effective_from=date(2026, 11, 1), effective_to=date(2026, 11, 30),
        )
        self.dealer_a = SalesSource.objects.create(name="甲車行", source_type="dealer")
        self.dealer_b = SalesSource.objects.create(name="乙車行", source_type="dealer")
        self.oil = DealerRewardCatalogItem.objects.create(reward_type="physical", name="機油", unit="罐")
        DealerRewardCostVersion.objects.create(catalog_item=self.oil, unit_cost=150, effective_from=date(2026, 1, 1))
        self.oil_campaign = DealerRewardCampaign.objects.create(
            name="四家車行 SUZUKI 油車送機油", brands=["SUZUKI"], energy_types=[GAS],
            effective_from=date(2026, 11, 1), effective_to=date(2026, 11, 30),
        )
        self.oil_campaign.dealers.set([self.dealer_a])
        DealerRewardCampaignItem.objects.create(campaign=self.oil_campaign, catalog_item=self.oil, reward_type="physical",
                                                name="機油", unit="罐", quantity=5, unit_cost_snapshot=150,
                                                cost_effective_on_snapshot=date(2026, 11, 1))
        self.voucher_campaign = DealerRewardCampaign.objects.create(name="全車行禮券", effective_from=date(2026, 1, 1))
        self.voucher_campaign.vehicle_models.set([self.model])
        DealerRewardCampaignItem.objects.create(campaign=self.voucher_campaign, reward_type="voucher", name="禮券",
                                                unit="元", quantity=1000)

    def order_with_vehicle(self, **kwargs):
        store = Store.objects.get_or_create(name="總店", code="HQ")[0]
        order = self.make_order(self.model, **kwargs)
        vehicle = VehicleInventory.objects.create(vehicle_model=self.model, color=order.color,
                                                  engine_number=f"ENG-{order.pk}", ownership_store=store,
                                                  location_store=store)
        order.allocate(vehicle)
        return order

    def save_registration(self, order, registration_date, plate="ABC-1234"):
        response = self.client.post(reverse("registration_save", args=[order.pk]),
                                    {"registration_date": registration_date, "final_plate_number": plate},
                                    HTTP_X_ORDER_WORKSPACE="1")
        self.assertEqual(response.status_code, 200, response.content[:300])
        order.refresh_from_db()

    def test_dealer_order_gets_rewards_on_registration_and_date_change_reapplies(self):
        order = self.order_with_vehicle(source=self.dealer_a, source_type=SalesOrder.SourceType.DEALER)
        self.save_registration(order, "2026-11-20")
        self.assertTrue(order.is_registration_complete)
        lines = list(order.dealer_reward_lines.order_by("campaign_id", "id")
                     .values_list("campaign_name", "name", "quantity", "dealer_id", "registration_date"))
        self.assertEqual(lines, [
            ("四家車行 SUZUKI 油車送機油", "機油", Decimal("5"), self.dealer_a.pk, date(2026, 11, 20)),
            ("全車行禮券", "禮券", Decimal("1000"), self.dealer_a.pk, date(2026, 11, 20)),
        ])
        profile = OrderOperationsProfile.objects.get(order=order)
        self.assertEqual(profile.sales_bonus, Decimal("2500"))
        # 人工改實銷獎勵後改領牌日到 12 月：加碼與機油消失，人工值保留。
        profile.installment_interest_subsidy = Decimal("321")
        profile.manual_financial_fields = sorted(set(profile.manual_financial_fields or []) | {"installment_interest_subsidy"})
        profile.save()
        self.save_registration(order, "2026-12-02")
        profile.refresh_from_db()
        self.assertEqual((profile.sales_bonus, profile.installment_interest_subsidy), (Decimal("2000"), Decimal("321")))
        self.assertEqual(list(order.dealer_reward_lines.values_list("name", flat=True)), ["禮券"])
        self.assertIsNotNone(profile.incentive_locked_at)
        page = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "registration"})
        self.assertContains(page, "車行獎勵")
        self.assertContains(page, "給 甲車行")
        self.assertContains(page, "SUZUKI 常態：實銷 $2,000／促銷 $0／分期 $0")
        self.assertNotContains(page, "11 月油車加碼")

    def test_dealer_scope_and_non_dealer_orders(self):
        other = self.order_with_vehicle(source=self.dealer_b, source_type=SalesOrder.SourceType.DEALER)
        self.save_registration(other, "2026-11-20")
        self.assertEqual(list(other.dealer_reward_lines.values_list("name", flat=True)), ["禮券"], "乙車行不在指定名單")
        platform = SalesSource.objects.create(name="平台", source_type="platform")
        web = self.order_with_vehicle(source=platform, source_type=SalesOrder.SourceType.PLATFORM)
        self.save_registration(web, "2026-11-20", plate="XYZ-0001")
        self.assertFalse(web.dealer_reward_lines.exists(), "網路平台單沒有車行獎勵")
        store = self.order_with_vehicle()
        SalesOrder.objects.filter(pk=store.pk).update(commission_recipient=self.dealer_a)
        store.refresh_from_db()
        self.save_registration(store, "2026-11-20", plate="XYZ-0002")
        self.assertEqual(store.dealer_reward_lines.count(), 2, "指定給車行的本店單照車行套用")

    def test_completed_orders_are_fixed_and_campaigns_in_use_are_protected(self):
        order = self.order_with_vehicle(source=self.dealer_a, source_type=SalesOrder.SourceType.DEALER)
        self.save_registration(order, "2026-11-20")
        with self.captureOnCommitCallbacks(execute=True):
            self.oil_campaign.items.update(quantity=9)
            self.oil_campaign.save()
        self.assertEqual(order.dealer_reward_lines.get(name="機油").quantity, Decimal("5"))
        apply_order_dealer_rewards(order)
        self.assertEqual(order.dealer_reward_lines.get(name="機油").quantity, Decimal("5"))
        response = self.client.post(reverse("dealer_reward_campaign_delete", args=[self.oil_campaign.pk]))
        self.assertRedirects(response, reverse("dealer_reward_campaign_edit", args=[self.oil_campaign.pk]))
        self.assertTrue(OrderDealerRewardLine.objects.filter(campaign=self.oil_campaign).exists())

    def test_pending_order_follows_campaign_until_registration(self):
        order = self.order_with_vehicle(source=self.dealer_a, source_type=SalesOrder.SourceType.DEALER)
        SalesOrder.objects.filter(pk=order.pk).update(registration_date=date(2026, 11, 20))
        order.refresh_from_db()
        apply_order_dealer_rewards(order)
        self.assertEqual(order.dealer_reward_lines.count(), 2)
        with self.captureOnCommitCallbacks(execute=True):
            self.oil_campaign.dealers.set([self.dealer_b])
        self.assertEqual(list(order.dealer_reward_lines.values_list("name", flat=True)), ["禮券"])


class DealerRewardCampaignScreenTests(CampaignFixtureMixin, TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", "", "test-pass-123")
        self.client.force_login(self.admin)
        self.model = self.make_model("SUZUKI", "NEX 125", GAS)
        self.dealer = SalesSource.objects.create(name="甲車行", source_type="dealer")
        self.oil = DealerRewardCatalogItem.objects.create(reward_type="physical", name="全合成機油", unit="罐")
        DealerRewardCostVersion.objects.create(catalog_item=self.oil, unit_cost=180, effective_from=date(2026, 1, 1))

    def payload(self, items=None, **overrides):
        items = items if items is not None else [(self.oil, "5")]
        data = {
            "name": "11 月送機油", "dealers": [self.dealer.pk], "brands": ["SUZUKI"], "energy_types": [GAS],
            "effective_from": "2026-11-01", "effective_to": "2026-11-30", "active": "on", "note": "",
            "reward_items-TOTAL_FORMS": str(len(items)), "reward_items-INITIAL_FORMS": "0",
            "reward_items-MIN_NUM_FORMS": "1", "reward_items-MAX_NUM_FORMS": "1000",
        }
        for index, (item, quantity) in enumerate(items):
            data[f"reward_items-{index}-catalog_item"] = str(item.pk)
            data[f"reward_items-{index}-quantity"] = quantity
            data[f"reward_items-{index}-note"] = ""
        data.update(overrides)
        return data

    def test_create_campaign_with_conditions_items_and_cost_snapshot(self):
        page = self.client.get(reverse("dealer_reward_campaign_create"), {"model": self.model.pk})
        self.assertContains(page, "全部電動類")
        self.assertContains(page, "＋ 新增品項")
        self.assertContains(page, 'data-reward-catalog=""')
        response = self.client.post(reverse("dealer_reward_campaign_create"), self.payload())
        self.assertRedirects(response, reverse("dealer_reward_campaign_list"))
        campaign = DealerRewardCampaign.objects.get()
        self.assertEqual((campaign.brands, campaign.energy_types, list(campaign.dealers.all())),
                         (["SUZUKI"], [GAS], [self.dealer]))
        item = campaign.items.get()
        self.assertEqual((item.display_label, item.unit_cost_snapshot, item.cost_effective_on_snapshot),
                         ("全合成機油 5 罐", Decimal("180"), date(2026, 11, 1)))
        listing = self.client.get(reverse("dealer_reward_campaign_list"))
        self.assertContains(listing, "全合成機油 5 罐")
        self.assertContains(listing, "甲車行")

    def test_duplicate_items_and_missing_conditions_are_rejected(self):
        duplicate = self.client.post(reverse("dealer_reward_campaign_create"),
                                     self.payload(items=[(self.oil, "1"), (self.oil, "2")]))
        self.assertContains(duplicate, "同一方案不可重複填寫相同獎勵")
        empty = self.client.post(reverse("dealer_reward_campaign_create"), self.payload(brands=[], energy_types=[]))
        self.assertContains(empty, "請至少選擇一個品牌、能源別或指定年式")
        self.assertFalse(DealerRewardCampaign.objects.exists())

    def test_quick_catalog_create_adds_item_and_cost(self):
        response = self.client.post(reverse("dealer_reward_catalog_quick_create"), {
            "quick-reward_type": "physical", "quick-name": "齒輪油", "quick-unit": "罐", "quick-unit_cost": "120",
            "quick-cost_from": "2026-11-01",
        })
        payload = response.json()
        self.assertTrue(payload["ok"])
        item = DealerRewardCatalogItem.objects.get(name="齒輪油")
        self.assertEqual((item.unit, payload["id"], payload["label"]), ("罐", item.pk, "齒輪油 · 實物／罐"))
        self.assertEqual(item.cost_versions.get().unit_cost, Decimal("120"))
        custom = self.client.post(reverse("dealer_reward_catalog_quick_create"), {
            "quick-reward_type": "physical", "quick-name": "安全帽", "quick-unit": "頂",
        }).json()
        self.assertTrue(custom["ok"])
        duplicate = self.client.post(reverse("dealer_reward_catalog_quick_create"), {
            "quick-reward_type": "physical", "quick-name": "齒輪油", "quick-unit": "罐",
        })
        self.assertEqual(duplicate.status_code, 400)

    def test_quick_catalog_needs_reward_operate_permission(self):
        from sales.access.models import ScreenAccessGrant, UserAccessState

        staff = get_user_model().objects.create_user("campaign-staff", password="test-pass-123")
        UserAccessState.objects.update_or_create(user=staff, defaults={"configured": True})
        ScreenAccessGrant.objects.create(user=staff, screen_key="commissions", view=True, operate=True)
        self.client.force_login(staff)
        page = self.client.get(reverse("dealer_reward_campaign_create"))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "＋ 新增品項")
        denied = self.client.post(reverse("dealer_reward_catalog_quick_create"), {
            "quick-reward_type": "physical", "quick-name": "不該建立", "quick-unit": "罐",
        })
        self.assertNotEqual(denied.status_code, 200)
        self.assertFalse(DealerRewardCatalogItem.objects.filter(name="不該建立").exists())

    def test_reward_entry_points_sit_together_under_rules(self):
        from sales.access.registry import SCREEN_GROUPS

        sections = dict(next(sections for key, _label, sections in SCREEN_GROUPS if key == "data"))
        self.assertIn("rewards", sections["費率與規則"])
        self.assertNotIn("rewards", sections["車輛與商品"])
        menu = self.client.get(reverse("dashboard")).content.decode()
        rules = menu.split('id="data-menu-rules"', 1)[1].split("</section>", 1)[0]
        self.assertIn("車行獎勵活動", rules)
        self.assertIn("車行獎勵品項", rules)
        maintenance = self.client.get(reverse("data_maintenance"))
        self.assertContains(maintenance, reverse("dealer_reward_campaign_list"))
        legacy_batch = self.client.get(reverse("vehicle_model_reward_batch"))
        self.assertRedirects(legacy_batch, reverse("dealer_reward_campaign_list"))
