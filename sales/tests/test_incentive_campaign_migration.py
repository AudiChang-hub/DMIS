"""資料遷移 0203（T-149）：原廠獎勵版本與車行附加獎勵方案一對一轉成活動；舊表不動，可反向刪除轉換出的活動。"""
from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, tag


@tag("migration")
class IncentiveCampaignConversionMigrationTests(TransactionTestCase):
    migrate_from = ("sales", "0202_incentive_campaigns")
    migrate_to = ("sales", "0203_convert_incentive_campaigns")

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])
        self.addCleanup(self._restore_latest_schema)

    def _restore_latest_schema(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def _apps(self, target):
        return MigrationExecutor(connection).loader.project_state([target]).apps

    def test_converts_versions_one_to_one_and_reverses(self):
        apps = self._apps(self.migrate_from)
        VehicleModel = apps.get_model("sales", "VehicleModel")
        Rule = apps.get_model("sales", "VehicleIncentiveRule")
        Plan = apps.get_model("sales", "DealerVehicleRewardPlan")
        Item = apps.get_model("sales", "DealerVehicleRewardItem")
        model = VehicleModel.objects.create(brand="SUZUKI", name="Gixxer 250", energy_type="gas", model_year=2023)
        rule = Rule.objects.create(vehicle_model=model, sales_bonus=5000, promotion_subsidy=5000,
                                   installment_interest_subsidy=6600, announced_on=date(2026, 9, 20),
                                   effective_from=date(2026, 10, 1), note="原廠公告", active=True)
        inactive = Rule.objects.create(vehicle_model=model, sales_bonus=100, announced_on=date(2026, 1, 1),
                                       effective_from=date(2026, 1, 1), effective_to=date(2026, 9, 30), active=False)
        plan = Plan.objects.create(vehicle_model=model, effective_from=date(2026, 10, 7), active=True)
        Item.objects.create(plan=plan, reward_type="voucher", name="郵政禮券", quantity=10000, unit="元",
                            unit_cost_snapshot=1, cost_effective_on_snapshot=date(2026, 10, 7))

        MigrationExecutor(connection).migrate([self.migrate_to])
        apps = self._apps(self.migrate_to)
        Campaign = apps.get_model("sales", "IncentiveCampaign")
        RewardCampaign = apps.get_model("sales", "DealerRewardCampaign")
        converted = Campaign.objects.get(legacy_rule_id=rule.pk)
        self.assertEqual(
            (converted.name, converted.kind, converted.sales_bonus, converted.promotion_subsidy,
             converted.installment_interest_subsidy, converted.effective_from, converted.effective_to,
             converted.announced_on, converted.note, converted.active, converted.source_types,
             converted.promotion_source_types, converted.brands, converted.energy_types),
            ("SUZUKI Gixxer 250 2023 年式 原廠獎勵", "regular", 5000, 5000, 6600, date(2026, 10, 1), None,
             date(2026, 9, 20), "原廠公告", True, [], ["platform"], [], []),
        )
        self.assertEqual(list(converted.vehicle_models.values_list("pk", flat=True)), [model.pk])
        self.assertFalse(Campaign.objects.get(legacy_rule_id=inactive.pk).active)
        reward = RewardCampaign.objects.get(legacy_plan_id=plan.pk)
        self.assertFalse(reward.dealers.exists())
        self.assertEqual(list(reward.items.values_list("name", "quantity", "unit_cost_snapshot")), [("郵政禮券", 10000, 1)])
        self.assertEqual(apps.get_model("sales", "VehicleIncentiveRule").objects.count(), 2, "舊表保留不動")

        MigrationExecutor(connection).migrate([self.migrate_from])
        apps = self._apps(self.migrate_from)
        self.assertEqual(apps.get_model("sales", "IncentiveCampaign").objects.count(), 0)
        self.assertEqual(apps.get_model("sales", "DealerRewardCampaign").objects.count(), 0)
        self.assertEqual(apps.get_model("sales", "VehicleIncentiveRule").objects.count(), 2)


@tag("migration")
class IncentiveCampaignConsolidationMigrationTests(TransactionTestCase):
    """資料遷移 0208（T-161）：轉換形狀的活動依品牌整理、舊活動停用保留；反向還原。"""

    migrate_from = ("sales", "0207_incentive_campaign_items")
    migrate_to = ("sales", "0208_consolidate_incentive_campaigns")

    def setUp(self):
        super().setUp()
        MigrationExecutor(connection).migrate([self.migrate_from])
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(
            MigrationExecutor(connection).loader.graph.leaf_nodes()))

    def _apps(self, target):
        return MigrationExecutor(connection).loader.project_state([target]).apps

    def test_consolidates_and_reverses(self):
        apps = self._apps(self.migrate_from)
        VehicleModel = apps.get_model("sales", "VehicleModel")
        Rule = apps.get_model("sales", "VehicleIncentiveRule")
        Campaign = apps.get_model("sales", "IncentiveCampaign")
        for name in ("Fun", "Run"):
            model = VehicleModel.objects.create(brand="eReady", name=name, energy_type="electric", model_year=2023)
            rule = Rule.objects.create(vehicle_model=model, sales_bonus=2000, promotion_subsidy=1500,
                                       announced_on=date(2026, 8, 1), effective_from=date(2026, 8, 1), active=True)
            campaign = Campaign.objects.create(name=f"eReady {name} 2023 年式 原廠獎勵", kind="regular", sales_bonus=2000,
                                               promotion_subsidy=1500, source_types=[], promotion_source_types=["platform"],
                                               brands=[], energy_types=[], effective_from=date(2026, 8, 1),
                                               announced_on=date(2026, 8, 1), legacy_rule_id=rule.pk)
            campaign.vehicle_models.add(model)

        MigrationExecutor(connection).migrate([self.migrate_to])
        Campaign = self._apps(self.migrate_to).get_model("sales", "IncentiveCampaign")
        created = Campaign.objects.filter(conversion_batch="t161").order_by("pk")
        self.assertEqual([c.name for c in created], ["eReady 原廠獎勵", "eReady 促銷補助（網路平台）"])
        self.assertEqual([sorted(c.items.values_list("item", "amount")) for c in created],
                         [[("sales_bonus", 2000)], [("promotion_subsidy", 1500)]])
        self.assertEqual(created[1].source_types, ["platform"])
        self.assertEqual(Campaign.objects.filter(conversion_batch="t161-merged", active=False).count(), 2)

        MigrationExecutor(connection).migrate([self.migrate_from])
        Campaign = self._apps(self.migrate_from).get_model("sales", "IncentiveCampaign")
        self.assertEqual(Campaign.objects.count(), 2)
        self.assertFalse(Campaign.objects.filter(active=False).exists())
        self.assertFalse(Campaign.objects.filter(name__startswith="（已整理）").exists())
