import importlib
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import (
    DealerRewardCatalogItem,
    DealerRewardCostVersion,
    DealerVehicleRewardItem,
    DealerVehicleRewardPlan,
    VehicleModel,
)


class DealerRewardCatalogTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("reward-catalog-test")
        self.client.force_login(self.user)
        self.list_url = reverse("dealer_reward_catalog_list")
        self.create_url = reverse("dealer_reward_catalog_create")

    def payload(self, *, name="全合成機油", unit="瓶", costs=None, **overrides):
        costs = costs or [("2026-09-01", "", "180", True, "九月進價")]
        data = {
            "reward_type": "physical",
            "name": name,
            "unit": unit,
            "active": "on",
            "note": "車行活動使用",
            "cost_versions-TOTAL_FORMS": str(len(costs)),
            "cost_versions-INITIAL_FORMS": "0",
            "cost_versions-MIN_NUM_FORMS": "1",
            "cost_versions-MAX_NUM_FORMS": "1000",
        }
        for index, (start, end, amount, active, note) in enumerate(costs):
            data.update(
                {
                    f"cost_versions-{index}-effective_from": start,
                    f"cost_versions-{index}-effective_to": end,
                    f"cost_versions-{index}-unit_cost": amount,
                    f"cost_versions-{index}-note": note,
                }
            )
            if active:
                data[f"cost_versions-{index}-active"] = "on"
        data.update(overrides)
        return data

    def test_create_catalog_item_with_effective_cost_version(self):
        form_page = self.client.get(self.create_url)
        self.assertContains(form_page, 'data-reward-catalog-form')
        self.assertContains(form_page, 'data-reward-unit=""')
        self.assertContains(form_page, 'data-cost-version-rows')
        self.assertContains(form_page, "新增成本版本")

        response = self.client.post(self.create_url, self.payload())

        self.assertRedirects(response, self.list_url)
        item = DealerRewardCatalogItem.objects.get()
        self.assertEqual(item.name, "全合成機油")
        self.assertEqual(item.unit, "瓶")
        self.assertEqual(
            item.cost_version_on(date(2026, 9, 15)).unit_cost,
            Decimal("180"),
        )

    def test_catalog_item_uses_shared_quick_active_toggle(self):
        item = DealerRewardCatalogItem.objects.create(
            reward_type="physical", name="快速停用品項", unit="瓶"
        )
        response = self.client.post(
            reverse(
                "master_record_set_active",
                args=["dealer-reward-catalog-item", item.pk],
            ),
            {"active": "0"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertFalse(item.active)

    def test_custom_unit_is_supported_but_wrong_standard_unit_is_rejected(self):
        custom = self.payload(name="保養耗材", unit="__other__")
        custom["unit_other"] = "桶"
        response = self.client.post(self.create_url, custom)
        self.assertRedirects(response, self.list_url)
        self.assertEqual(DealerRewardCatalogItem.objects.get().unit, "桶")

        wrong = self.payload(
            name="旅遊累計",
            unit="瓶",
            reward_type="travel_points",
        )
        response = self.client.post(self.create_url, wrong)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "請選擇符合獎勵類型的單位")
        self.assertEqual(DealerRewardCatalogItem.objects.count(), 1)

    def test_overlapping_cost_versions_are_rejected_atomically(self):
        response = self.client.post(
            self.create_url,
            self.payload(
                costs=[
                    ("2026-09-01", "2026-09-30", "180", True, "第一版"),
                    ("2026-09-15", "", "200", True, "重疊版"),
                ]
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "啟用中的成本版本期間不可重疊")
        self.assertFalse(DealerRewardCatalogItem.objects.exists())
        self.assertFalse(DealerRewardCostVersion.objects.exists())

    def test_active_and_inactive_items_are_separated_into_tabs(self):
        active = DealerRewardCatalogItem.objects.create(
            reward_type="physical", name="啟用機油", unit="瓶"
        )
        inactive = DealerRewardCatalogItem.objects.create(
            reward_type="voucher", name="停用禮券", unit="張", active=False
        )
        DealerRewardCostVersion.objects.create(
            catalog_item=active,
            effective_from=date(2026, 1, 1),
            unit_cost=150,
        )

        response = self.client.get(self.list_url)
        self.assertContains(response, "啟用機油")
        self.assertNotContains(response, "停用禮券")
        self.assertContains(response, "目前單位成本")
        self.assertContains(response, "dealer-reward-catalog-item")

        response = self.client.get(self.list_url, {"status": "inactive"})
        self.assertContains(response, "停用禮券")
        self.assertNotContains(response, "啟用機油")

    def test_navigation_help_and_mobile_shortcut_expose_daily_master(self):
        maintenance = self.client.get(reverse("data_maintenance"))
        self.assertContains(maintenance, self.list_url)
        self.assertContains(maintenance, "車行獎勵品項")

        dashboard = self.client.get(reverse("dashboard"))
        self.assertContains(dashboard, 'value="dealer-reward-items"')

        guide = self.client.get(reverse("user_guide"))
        self.assertContains(guide, "日常資料 → 車行獎勵品項")

        base = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
            encoding="utf-8"
        )
        self.assertLess(
            base.index("{% url 'dealer_reward_catalog_list' %}"),
            base.index('id="data-menu-rules"'),
        )

    def test_existing_reward_rows_are_converted_to_shared_catalog_items(self):
        vehicle_model = VehicleModel.objects.create(
            brand="SUZUKI",
            name="舊獎勵測試車",
            model_number="OLD-RW",
            model_year=2026,
            model_code=VehicleModel.ModelType.DISC,
            energy_type=VehicleModel.EnergyType.GAS,
            displacement_cc=125,
        )
        plan = DealerVehicleRewardPlan.objects.create(
            vehicle_model=vehicle_model,
            effective_from=date(2026, 1, 1),
        )
        reward = DealerVehicleRewardItem.objects.create(
            plan=plan,
            reward_type="physical",
            name="舊資料機油",
            quantity=2,
            unit="瓶",
        )
        migration = importlib.import_module(
            "sales.migrations.0119_dealer_reward_catalog_costs"
        )

        migration.create_catalog_items_for_existing_rewards(apps, None)

        reward.refresh_from_db()
        self.assertIsNotNone(reward.catalog_item_id)
        self.assertEqual(reward.catalog_item.name, "舊資料機油")
        self.assertEqual(reward.catalog_item.unit, "瓶")
