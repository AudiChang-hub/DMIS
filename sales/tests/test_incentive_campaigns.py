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
    OrderChange,
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
from sales.tests.campaign_helpers import convert_legacy_versions, make_campaign

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

        # 0203 一對一轉成活動；0208 逐筆轉成項目列，促銷只給平台的拆出兄弟活動（平台給促銷、其他通路促銷 0）。
        self.assertEqual(IncentiveCampaign.objects.filter(legacy_rule__isnull=False).count(),
                         VehicleIncentiveRule.objects.count())
        for (model_id, day, source), expected in before.items():
            model = VehicleModel.objects.get(pk=model_id)
            _rows, totals, _matched, _promo, _regular = incentive_totals(model, source, day)
            self.assertEqual({key: Decimal(value) for key, value in expected.items()}, totals,
                             f"{model} {day} {source}")
        campaign = IncentiveCampaign.objects.get(legacy_rule__vehicle_model=gixxer)
        self.assertEqual((campaign.kind, campaign.source_types, campaign.item_amounts()),
                         ("regular", ["store", "dealer", "platform"],
                          {"sales_bonus": Decimal("5000"), "installment_interest_subsidy": Decimal("6600")}))
        siblings = IncentiveCampaign.objects.filter(vehicle_models=gixxer, legacy_rule__isnull=True).order_by("pk")
        self.assertEqual([(c.source_types, c.item_amounts()) for c in siblings],
                         [(["platform"], {"promotion_subsidy": Decimal("5000")}),
                          (["store", "dealer"], {"promotion_subsidy": Decimal("0")})])
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


class ConsolidationTests(CampaignFixtureMixin, TestCase):
    """T-161：正式站形狀的 17 筆依品牌整理成 11 筆；每個年式 × 日期 × 通路結果與整理前相同，舊活動停用保留。"""

    def test_production_shape_consolidates_to_approved_list_with_identical_results(self):
        from django.apps import apps

        from sales.tests.campaign_helpers import _migration

        spec = [
            ("SUZUKI", "SUI 125", GAS, 2026, 2000, 1500, 0, date(2026, 10, 1), date(2026, 10, 1)),
            ("SUZUKI", "Saluto 125", GAS, 2026, 2000, 1500, 0, date(2026, 10, 1), date(2026, 10, 1)),
            ("SUZUKI", "New NEX 125", GAS, 2026, 2000, 1500, 0, date(2026, 10, 1), date(2026, 10, 1)),
            ("SUZUKI", "Swish 125", GAS, 2026, 2000, 1500, 0, date(2026, 10, 1), date(2026, 10, 1)),
            ("eReady", "Fun", ELECTRIC, 2023, 2000, 1500, 0, date(2026, 8, 1), date(2026, 8, 1)),
            ("GOGORO", "EZZY", LIGHT, 2025, 1000, 1500, 0, date(2026, 10, 1), date(2026, 10, 1)),
            ("GOGORO", "Gogoro Delight", ELECTRIC, 2021, 1000, 1500, 0, date(2026, 10, 1), date(2026, 10, 15)),
            ("eMOVING", "EZ1", LIGHT, 2021, 5000, 0, 0, date(2026, 10, 1), date(2026, 10, 1)),
            ("SUZUKI", "Gixxer 250", GAS, 2023, 5000, 5000, 6600, date(2026, 10, 1), date(2026, 10, 1)),
        ]
        models = []
        for brand, name, energy, year, sales, promo, interest, start, announced in spec:
            model = self.make_model(brand, name, energy, year)
            models.append(model)
            VehicleIncentiveRule.objects.create(vehicle_model=model, sales_bonus=sales, promotion_subsidy=promo,
                                                installment_interest_subsidy=interest, effective_from=start,
                                                announced_on=announced)
        other = self.make_model("SUZUKI", "Gixxer SF 250", GAS, 2023)  # 同品牌沒有獎勵的年式不可被帶到
        models.append(other)
        days = [date(2026, 7, 31), date(2026, 8, 15), date(2026, 10, 1), date(2026, 11, 30)]
        before = {(m.pk, d, s): _old_amounts(_old_resolve(m.pk, d), s)
                  for m in models for d in days for s in ("platform", "dealer", "store")}
        _migration("_convert_incentive_campaigns").convert(apps, None)
        legacy_ids = set(IncentiveCampaign.objects.values_list("pk", flat=True))
        plan = _migration("_consolidate_incentive_campaigns").build_plan(apps)
        self.assertEqual(plan["mode"], "consolidate")
        _migration("_consolidate_incentive_campaigns").forwards(apps, None)

        created = IncentiveCampaign.objects.exclude(pk__in=legacy_ids).order_by("pk")
        self.assertEqual([c.name for c in created], [
            "SUZUKI 速克達 原廠獎勵", "SUZUKI 速克達 促銷補助（網路平台）", "eReady Fun 原廠獎勵", "eReady Fun 促銷補助（網路平台）",
            "GOGORO 原廠獎勵", "GOGORO 促銷補助（網路平台）", "eMOVING EZ1 原廠獎勵",
            "Gixxer 250 原廠獎勵", "Gixxer 250 促銷補助（網路平台）",
        ])
        gogoro = created.get(name="GOGORO 原廠獎勵")
        self.assertEqual((gogoro.note, gogoro.announced_on, gogoro.source_types),
                         ("Delight 2021 公告日 10/15", date(2026, 10, 1), ["store", "dealer", "platform"]))
        self.assertEqual(created.get(name="Gixxer 250 原廠獎勵").item_amounts(),
                         {"sales_bonus": Decimal("5000"), "installment_interest_subsidy": Decimal("6600")})
        self.assertEqual(created.get(name="eReady Fun 促銷補助（網路平台）").source_types, ["platform"])
        retired = IncentiveCampaign.objects.filter(pk__in=legacy_ids)
        self.assertFalse(retired.filter(active=True).exists())
        self.assertTrue(all(c.name.startswith("（已整理）") and "已整理至：" in c.note for c in retired))
        for (model_id, day, source), expected in before.items():
            model = VehicleModel.objects.get(pk=model_id)
            _rows, totals, _m, _p, _r = incentive_totals(model, source, day)
            self.assertEqual({k: Decimal(v) for k, v in expected.items()}, totals, f"{model} {day} {source}")

        _migration("_consolidate_incentive_campaigns").backwards(apps, None)
        self.assertEqual(set(IncentiveCampaign.objects.values_list("pk", flat=True)), legacy_ids)
        self.assertFalse(IncentiveCampaign.objects.filter(name__startswith="（已整理）").exists())
        self.assertFalse(IncentiveCampaign.objects.filter(active=False).exists())


class IncentiveCampaignApplyTests(CampaignFixtureMixin, TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", "", "test-pass-123")
        self.client.force_login(self.admin)
        self.fun = self.make_model("eReady", "Fun", ELECTRIC, 2023)
        self.sui = self.make_model("SUZUKI", "SUI 125", GAS)
        self.regular = make_campaign(name="Fun 原廠獎勵", items={"sales_bonus": 2000}, vehicle_models=[self.fun],
                                     effective_from=date(2026, 8, 1))
        self.platform_promo = make_campaign(name="Fun 促銷（網路平台）", items={"promotion_subsidy": 1500},
                                            vehicle_models=[self.fun], source_types=["platform"],
                                            effective_from=date(2026, 8, 1))
        self.bonus = make_campaign(
            name="11 月特簽加碼", kind=IncentiveCampaign.Kind.BONUS, items={"promotion_subsidy": 500},
            energy_types=[ELECTRIC, LIGHT, MICRO], effective_from=date(2026, 11, 1), effective_to=date(2026, 11, 30),
        )

    def test_regular_items_and_bonus_are_added_and_breakdown_is_saved(self):
        order = self.make_order(self.fun, source_type=SalesOrder.SourceType.PLATFORM, registration_date=date(2026, 11, 15))
        profile = apply_order_incentive_rule(order)
        self.assertEqual((profile.sales_bonus, profile.promotion_subsidy), (Decimal("2000"), Decimal("2000")))
        rows = list(profile.incentive_applications.order_by("campaign_id").values_list(
            "campaign_name", "kind", "sales_bonus", "promotion_subsidy"))
        self.assertEqual(rows, [("Fun 原廠獎勵", "regular", Decimal("2000"), Decimal("0")),
                                ("Fun 促銷（網路平台）", "regular", Decimal("0"), Decimal("1500")),
                                ("11 月特簽加碼", "bonus", Decimal("0"), Decimal("500"))])

    def test_channels_apply_to_every_item_of_the_campaign(self):
        store_order = self.make_order(self.fun, registration_date=date(2026, 11, 15))
        profile = apply_order_incentive_rule(store_order)
        # 促銷常態只勾網路平台；加碼三個通路全勾，所以本店單只拿到加碼 500。
        self.assertEqual((profile.sales_bonus, profile.promotion_subsidy), (Decimal("2000"), Decimal("500")))

    def test_newer_regular_with_one_item_does_not_wipe_other_items(self):
        make_campaign(name="Fun 實銷調整", items={"sales_bonus": 2500}, vehicle_models=[self.fun],
                      effective_from=date(2026, 11, 1))
        order = self.make_order(self.fun, source_type=SalesOrder.SourceType.PLATFORM, registration_date=date(2026, 11, 15))
        profile = apply_order_incentive_rule(order)
        self.assertEqual((profile.sales_bonus, profile.promotion_subsidy), (Decimal("2500"), Decimal("2000")))
        make_campaign(name="Fun 促銷歸零", items={"promotion_subsidy": 0}, vehicle_models=[self.fun],
                      source_types=["platform"], effective_from=date(2026, 11, 10))
        profile = apply_order_incentive_rule(order)
        self.assertEqual(profile.promotion_subsidy, Decimal("500"), "填 0 的新常態把常態促銷歸零，加碼照加")

    def test_no_channel_pauses_campaign(self):
        IncentiveCampaign.objects.filter(pk=self.bonus.pk).update(source_types=[])
        order = self.make_order(self.fun, source_type=SalesOrder.SourceType.PLATFORM, registration_date=date(2026, 11, 15))
        self.assertEqual(apply_order_incentive_rule(order).promotion_subsidy, Decimal("1500"))
        listing = self.client.get(reverse("incentive_rule_list"), {"status": "paused"})
        self.assertContains(listing, "11 月特簽加碼")
        self.assertContains(listing, "已暫停（未選通路）")
        self.assertNotContains(listing, "Fun 原廠獎勵")

    def test_dealer_condition_uses_payment_dealer_including_assigned_store_orders(self):
        dealer_a = SalesSource.objects.create(name="甲車行", source_type="dealer")
        dealer_b = SalesSource.objects.create(name="乙車行", source_type="dealer")
        make_campaign(name="甲車行加碼", kind=IncentiveCampaign.Kind.BONUS, items={"sales_bonus": 300},
                      vehicle_models=[self.sui], dealers=[dealer_a],
                      effective_from=date(2026, 11, 1), effective_to=date(2026, 11, 30))
        day = date(2026, 11, 15)
        self.assertEqual(apply_order_incentive_rule(self.make_order(
            self.sui, source=dealer_a, source_type=SalesOrder.SourceType.DEALER, registration_date=day)).sales_bonus, 300)
        self.assertEqual(apply_order_incentive_rule(self.make_order(
            self.sui, source=dealer_b, source_type=SalesOrder.SourceType.DEALER, registration_date=day)).sales_bonus, 0)
        assigned = self.make_order(self.sui, registration_date=day)
        SalesOrder.objects.filter(pk=assigned.pk).update(commission_recipient=dealer_a)
        assigned.refresh_from_db()
        self.assertEqual(apply_order_incentive_rule(assigned).sales_bonus, 300, "指定給甲車行的本店單也套用")
        SalesOrder.objects.filter(pk=assigned.pk).update(commission_recipient=dealer_b)
        assigned.refresh_from_db()
        self.assertEqual(apply_order_incentive_rule(assigned).sales_bonus, 0)
        self.assertEqual(apply_order_incentive_rule(self.make_order(
            self.sui, source_type=SalesOrder.SourceType.PLATFORM, registration_date=day)).sales_bonus, 300,
            "網路平台單不看車行條件")

    def test_campaign_left_without_conditions_matches_nothing(self):
        orphan = make_campaign(name="孤兒活動", items={"sales_bonus": 9999}, effective_from=date(2026, 1, 1))
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
        self.bonus.items.update(amount=900)
        _refresh_campaign_orders()
        self.assertEqual(apply_order_incentive_rule(order).promotion_subsidy, Decimal("2000"))

    def test_pending_orders_refresh_after_campaign_change(self):
        order = self.make_order(self.fun, source_type=SalesOrder.SourceType.PLATFORM, registration_date=date(2026, 11, 15))
        apply_order_incentive_rule(order)
        with self.captureOnCommitCallbacks(execute=True):
            item = self.bonus.items.get()
            item.amount = 800
            item.save()
            self.bonus.save()
        self.assertEqual(OrderOperationsProfile.objects.get(order=order).promotion_subsidy, Decimal("2300"))

    def test_used_campaign_cannot_be_deleted(self):
        order = self.make_order(self.fun, source_type=SalesOrder.SourceType.PLATFORM, registration_date=date(2026, 11, 15))
        apply_order_incentive_rule(order)
        response = self.client.post(reverse("incentive_campaign_delete", args=[self.bonus.pk]))
        self.assertRedirects(response, reverse("incentive_campaign_edit", args=[self.bonus.pk]))
        self.assertTrue(IncentiveCampaign.objects.filter(pk=self.bonus.pk).exists())

    def campaign_post(self, items=(("promotion_subsidy", "500"),), **overrides):
        data = {
            "name": "測試活動", "kind": "bonus", "source_types": ["store", "dealer", "platform"], "dealer_mode": "all",
            "energy_types": [ELECTRIC], "announced_on": "2026-11-01", "effective_from": "2026-11-01",
            "effective_to": "2026-11-30", "active": "on", "note": "",
            "items-TOTAL_FORMS": str(len(items)), "items-INITIAL_FORMS": "0", "items-MIN_NUM_FORMS": "1",
            "items-MAX_NUM_FORMS": "1000",
        }
        for index, (item, amount) in enumerate(items):
            data[f"items-{index}-item"] = item
            data[f"items-{index}-amount"] = amount
        data.update(overrides)
        return self.client.post(reverse("incentive_campaign_create"), data)

    def test_form_creates_campaign_with_item_rows_and_validates(self):
        page = self.client.get(reverse("incentive_campaign_create"))
        self.assertContains(page, "＋ 新增項目")
        self.assertNotContains(page, "促銷補助給哪些通路")
        self.assertEqual(page.context["form"].initial["source_types"], ["store", "dealer", "platform"])
        response = self.campaign_post(items=(("sales_bonus", "300"), ("promotion_subsidy", "500")))
        self.assertRedirects(response, reverse("incentive_rule_list"))
        campaign = IncentiveCampaign.objects.get(name="測試活動")
        self.assertEqual(campaign.item_amounts(), {"sales_bonus": Decimal("300"), "promotion_subsidy": Decimal("500")})
        self.assertEqual((campaign.source_types, list(campaign.dealers.all())), (["store", "dealer", "platform"], []))

        dup = self.campaign_post(name="重複項目", items=(("sales_bonus", "1"), ("sales_bonus", "2")))
        self.assertContains(dup, "同一個項目只能有一列")
        none = self.campaign_post(name="沒有項目", items=(), **{"items-TOTAL_FORMS": "0"})
        self.assertContains(none, "請至少")
        no_dealer = self.campaign_post(name="指定沒選", dealer_mode="selected")
        self.assertContains(no_dealer, "請至少選一家車行")
        disjoint = self.campaign_post(name="沒有交集", brands=["SUZUKI"], energy_types=[ELECTRIC])
        self.assertContains(disjoint, "沒有任何年式符合")
        self.assertEqual(IncentiveCampaign.objects.filter(name__in=["重複項目", "沒有項目", "指定沒選", "沒有交集"]).count(), 0)

    def test_form_allows_no_channel_as_paused_with_warning(self):
        response = self.campaign_post(name="暫停活動", source_types=[], follow=False)
        self.assertRedirects(response, reverse("incentive_rule_list"), fetch_redirect_response=False)
        campaign = IncentiveCampaign.objects.get(name="暫停活動")
        self.assertTrue(campaign.is_paused)
        page = self.client.get(reverse("incentive_rule_list"))
        self.assertContains(page, "沒有勾選任何通路，已暫停")
        form_page = self.client.get(reverse("incentive_campaign_edit", args=[campaign.pk]))
        self.assertContains(form_page, "data-paused-confirm")

    def test_form_selected_dealers_are_saved_and_cleared(self):
        dealer = SalesSource.objects.create(name="甲車行", source_type="dealer")
        self.campaign_post(name="指定車行", dealer_mode="selected", dealers=[dealer.pk])
        campaign = IncentiveCampaign.objects.get(name="指定車行")
        self.assertEqual(list(campaign.dealers.all()), [dealer])
        item = campaign.items.get()
        data = {
            "name": "指定車行", "kind": "bonus", "source_types": ["dealer"], "dealer_mode": "all",
            "dealers": [dealer.pk], "energy_types": [ELECTRIC], "announced_on": "2026-11-01",
            "effective_from": "2026-11-01", "effective_to": "2026-11-30", "active": "on", "note": "",
            "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "1", "items-MIN_NUM_FORMS": "1",
            "items-MAX_NUM_FORMS": "1000", "items-0-id": str(item.pk), "items-0-item": "promotion_subsidy",
            "items-0-amount": "600",
        }
        self.client.post(reverse("incentive_campaign_edit", args=[campaign.pk]), data)
        campaign.refresh_from_db()
        self.assertFalse(campaign.dealers.exists(), "改回全部車行要清掉指定名單")
        self.assertEqual(campaign.item_amounts(), {"promotion_subsidy": Decimal("600")})

    def test_same_day_regular_conflict_is_per_item(self):
        ok = self.campaign_post(name="同日不同項目", kind="regular", effective_from="2026-08-01", effective_to="",
                                energy_types=[], vehicle_models=[self.fun.pk], items=(("installment_interest_subsidy", "100"),))
        self.assertRedirects(ok, reverse("incentive_rule_list"))
        clash = self.campaign_post(name="同日同項目", kind="regular", effective_from="2026-08-01", effective_to="",
                                   energy_types=[], vehicle_models=[self.fun.pk], items=(("sales_bonus", "100"),))
        self.assertContains(clash, "已有同一天開始、涵蓋相同年式且有相同項目的常態活動：Fun 原廠獎勵")

    def test_list_fuzzy_model_search_marks_hit_models(self):
        response = self.client.get(reverse("incentive_rule_list"), {"q": "fun"})
        self.assertContains(response, "Fun 原廠獎勵")
        self.assertContains(response, "11 月特簽加碼")
        self.assertContains(response, 'aria-label="命中的年式"')
        self.assertContains(response, "eReady Fun 2023")
        miss = self.client.get(reverse("incentive_rule_list"), {"q": "sui"})
        self.assertNotContains(miss, "Fun 原廠獎勵")
        partial = self.client.get(reverse("incentive_rule_list"), {"q": "fun"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertNotContains(partial, "<html")
        self.assertContains(partial, "Fun 原廠獎勵")

    def test_list_workspace_show_campaign_items(self):
        listing = self.client.get(reverse("incentive_rule_list"))
        self.assertContains(listing, "促銷補助金 1,500")
        tab = self.client.get(reverse("vehicle_model_incentives", args=[self.fun.pk]))
        self.assertContains(tab, "Fun 原廠獎勵")
        self.assertContains(tab, "實銷獎勵金 2,000")
        self.assertNotContains(self.client.get(reverse("vehicle_model_incentives", args=[self.sui.pk])), "Fun 原廠獎勵")


class IncentiveBackfillTests(CampaignFixtureMixin, TestCase):
    """回溯（T-161）：只讀掃描、逐張勾選覆寫、OrderChange、權限、匯入單不列、預覽後被改就整批不寫。"""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", "", "test-pass-123")
        self.client.force_login(self.admin)
        self.sui = self.make_model("SUZUKI", "SUI 125", GAS)
        self.dealer = SalesSource.objects.create(name="甲車行", source_type="dealer")
        self.old = self.make_order(self.sui, source=self.dealer, source_type=SalesOrder.SourceType.DEALER,
                                   registration_date=date(2026, 11, 3))
        apply_order_incentive_rule(self.old, "tester", lock=True)  # 活動建立前已領牌固定：0 元
        self.pending = self.make_order(self.sui, source=self.dealer, source_type=SalesOrder.SourceType.DEALER,
                                       registration_date=date(2026, 11, 5))
        apply_order_incentive_rule(self.pending)
        self.campaign = make_campaign(name="11 月 SUI 加碼", kind=IncentiveCampaign.Kind.BONUS,
                                      items={"sales_bonus": 800}, vehicle_models=[self.sui], refresh=False,
                                      effective_from=date(2026, 11, 1), effective_to=date(2026, 11, 30))
        self.url = reverse("incentive_campaign_backfill", args=[self.campaign.pk])

    def test_scan_is_read_only_and_flags_locked_orders(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        rows = {row["order"].pk: row for row in response.context["rows"]}
        self.assertEqual(set(rows), {self.old.pk, self.pending.pk})
        self.assertTrue(rows[self.old.pk]["locked"])
        self.assertFalse(rows[self.old.pk]["default_checked"], "已固定的單預設不勾")
        self.assertTrue(rows[self.pending.pk]["default_checked"])
        self.assertEqual(rows[self.old.pk]["after"]["sales_bonus"], Decimal("800"))
        self.assertContains(response, "已領牌固定")
        self.assertEqual(OrderOperationsProfile.objects.get(order=self.old).sales_bonus, Decimal("0"), "掃描不寫入")

    def test_apply_overwrites_only_checked_orders_with_order_change(self):
        rows = {row["order"].pk: row for row in self.client.get(self.url).context["rows"]}
        response = self.client.post(self.url, {"order": [self.old.pk], f"token_{self.old.pk}": rows[self.old.pk]["token"]})
        self.assertRedirects(response, reverse("incentive_rule_list"))
        old = OrderOperationsProfile.objects.get(order=self.old)
        self.assertEqual(old.sales_bonus, Decimal("800"))
        self.assertIsNotNone(old.incentive_locked_at, "覆寫後維持固定")
        self.assertEqual(list(old.incentive_applications.values_list("campaign_name", flat=True)), ["11 月 SUI 加碼"])
        change = OrderChange.objects.get(order=self.old, reason__startswith="原廠獎勵活動回溯")
        self.assertEqual(change.changes["實銷獎勵金"], {"before": "0", "after": "800"})
        self.assertEqual(OrderOperationsProfile.objects.get(order=self.pending).sales_bonus, Decimal("0"), "沒勾的不動")

    def test_manual_values_are_flagged_and_released_when_overwritten(self):
        profile = OrderOperationsProfile.objects.get(order=self.pending)
        profile.sales_bonus = Decimal("123")
        profile.manual_financial_fields = ["sales_bonus", "vehicle_cost"]
        profile.save()
        rows = {row["order"].pk: row for row in self.client.get(self.url).context["rows"]}
        self.assertEqual(rows[self.pending.pk]["manual"], ["實銷獎勵金"])
        self.assertFalse(rows[self.pending.pk]["default_checked"])
        self.client.post(self.url, {"order": [self.pending.pk], f"token_{self.pending.pk}": rows[self.pending.pk]["token"]})
        profile.refresh_from_db()
        self.assertEqual((profile.sales_bonus, profile.manual_financial_fields), (Decimal("800"), ["vehicle_cost"]))

    def test_stale_preview_writes_nothing(self):
        rows = {row["order"].pk: row for row in self.client.get(self.url).context["rows"]}
        OrderOperationsProfile.objects.filter(order=self.pending).update(sales_bonus=55)
        self.client.post(self.url, {"order": [self.old.pk, self.pending.pk],
                                    f"token_{self.old.pk}": rows[self.old.pk]["token"],
                                    f"token_{self.pending.pk}": rows[self.pending.pk]["token"]})
        self.assertEqual(OrderOperationsProfile.objects.get(order=self.old).sales_bonus, Decimal("0"))
        self.assertFalse(OrderChange.objects.filter(reason__startswith="原廠獎勵活動回溯").exists())

    def test_imported_cancelled_and_out_of_scope_orders_are_not_listed(self):
        from sales.models import LegacyImportBatch, LegacyImportRow, LegacySalesSnapshot

        imported = self.make_order(self.sui, source=self.dealer, source_type=SalesOrder.SourceType.DEALER,
                                   registration_date=date(2026, 11, 6))
        batch = LegacyImportBatch.objects.create(import_type="operations", original_filename="synthetic.xlsx", file_size=0)
        row = LegacyImportRow.objects.create(batch=batch, sheet_name="銷貨", source_row=4, raw_data={}, mapped_data={})
        LegacySalesSnapshot.objects.create(order=imported, import_row=row)
        cancelled = self.make_order(self.sui, source=self.dealer, source_type=SalesOrder.SourceType.DEALER,
                                    registration_date=date(2026, 11, 6))
        SalesOrder.objects.filter(pk=cancelled.pk).update(status=SalesOrder.Status.CANCELLED)
        outside = self.make_order(self.sui, source=self.dealer, source_type=SalesOrder.SourceType.DEALER,
                                  registration_date=date(2026, 12, 1))
        listed = {row["order"].pk for row in self.client.get(self.url).context["rows"]}
        self.assertFalse(listed & {imported.pk, cancelled.pk, outside.pk})

    def test_overwrite_needs_both_operate_permissions(self):
        from sales.access.models import ScreenAccessGrant, UserAccessState

        staff = get_user_model().objects.create_user("backfill-staff", password="test-pass-123")
        UserAccessState.objects.update_or_create(user=staff, defaults={"configured": True})
        ScreenAccessGrant.objects.create(user=staff, screen_key="incentives", view=True, operate=True)
        self.client.force_login(staff)
        page = self.client.get(self.url)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "覆寫勾選的訂單")
        rows = {row["order"].pk: row for row in page.context["rows"]}
        denied = self.client.post(self.url, {"order": [self.pending.pk], f"token_{self.pending.pk}": rows[self.pending.pk]["token"]})
        self.assertEqual(denied.status_code, 403)
        ScreenAccessGrant.objects.create(user=staff, screen_key="order_finance", view=True, operate=True)
        self.client.post(self.url, {"order": [self.pending.pk], f"token_{self.pending.pk}": rows[self.pending.pk]["token"]})
        self.assertEqual(OrderOperationsProfile.objects.get(order=self.pending).sales_bonus, Decimal("800"))


class RegistrationFlowTests(CampaignFixtureMixin, TestCase):
    """經由領牌存檔：填好即完成並固定；改領牌日依新日期重新套用，人工值保留（T-147）。"""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", "", "test-pass-123")
        self.client.force_login(self.admin)
        self.model = self.make_model("SUZUKI", "Saluto 125", GAS)
        VehicleSettlementCostRule.objects.create(vehicle_model=self.model, amount=Decimal("60000"),
                                                 effective_from=date(2026, 1, 1))
        make_campaign(name="SUZUKI 常態", brands=["SUZUKI"], items={"sales_bonus": 2000},
                      effective_from=date(2026, 1, 1))
        self.november = make_campaign(
            name="11 月油車加碼", kind=IncentiveCampaign.Kind.BONUS, energy_types=[GAS], items={"sales_bonus": 500},
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
        self.assertIn("<strong>車行傭金與獎勵</strong>", rules)
        self.assertNotIn("<strong>車行獎勵品項</strong>", rules)
        maintenance = self.client.get(reverse("data_maintenance"))
        self.assertContains(maintenance, "<h2>車行傭金與獎勵</h2>", html=False)
        # T-162：活動從共用入口的分頁列進入。
        campaign_tab = f'<a href="{reverse("dealer_reward_campaign_list")}">獎勵活動</a>'
        self.assertContains(self.client.get(reverse("dealer_sales_program_list")), campaign_tab, html=False)
        legacy_batch = self.client.get(reverse("vehicle_model_reward_batch"))
        self.assertRedirects(legacy_batch, reverse("dealer_reward_campaign_list"))
