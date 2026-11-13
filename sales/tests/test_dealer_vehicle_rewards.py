from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import (
    DealerRewardCampaign,
    DealerRewardCampaignItem,
    DealerRewardCatalogItem,
    DealerRewardCostVersion,
    VehicleModel,
)


class DealerVehicleRewardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("reward-test")
        cls.model = VehicleModel.objects.create(
            brand="SUZUKI",
            name="獎勵測試車",
            model_number="RW001",
            model_year=2026,
            model_code=VehicleModel.ModelType.DISC,
            energy_type=VehicleModel.EnergyType.GAS,
            displacement_cc=125,
            base_dealer_commission=1200,
        )
        cls.physical_item = DealerRewardCatalogItem.objects.create(
            reward_type="physical", name="全合成機油", unit="瓶"
        )
        cls.travel_item = DealerRewardCatalogItem.objects.create(
            reward_type="travel_points", name="國內旅遊", unit="點"
        )
        cls.voucher_item = DealerRewardCatalogItem.objects.create(
            reward_type="voucher", name="禮券", unit="元"
        )
        DealerRewardCostVersion.objects.create(
            catalog_item=cls.physical_item,
            effective_from=date(2026, 1, 1),
            unit_cost=180,
        )
        DealerRewardCostVersion.objects.create(
            catalog_item=cls.travel_item,
            effective_from=date(2026, 1, 1),
            unit_cost=25,
        )
        DealerRewardCostVersion.objects.create(
            catalog_item=cls.voucher_item,
            effective_from=date(2026, 1, 1),
            unit_cost=500,
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("vehicle_model_commission", args=[self.model.pk])

    def make_campaign(self, *items, **fields):
        """車行附加獎勵改為活動制（T-149）：指定本年式、全部車行、今天有效的活動。"""
        campaign = DealerRewardCampaign.objects.create(name=fields.pop("name", "九月方案"),
                                                       effective_from=fields.pop("effective_from", date(2026, 1, 1)),
                                                       **fields)
        campaign.vehicle_models.set([self.model])
        for reward_type, name, quantity, unit in items:
            DealerRewardCampaignItem.objects.create(campaign=campaign, reward_type=reward_type, name=name,
                                                    quantity=quantity, unit=unit)
        return campaign

    def test_page_is_bound_to_vehicle_and_lists_reward_campaigns_read_only(self):
        self.make_campaign(("physical", "全合成機油", 2, "瓶"), name="九月送機油")
        response = self.client.get(self.url)
        self.assertContains(response, "車行傭金與銷售獎勵")
        self.assertContains(response, "車行基礎傭金")
        self.assertContains(response, "車行獎勵活動")
        self.assertContains(response, "九月送機油")
        self.assertContains(response, "全合成機油 2 瓶")
        self.assertContains(response, f'{reverse("dealer_reward_campaign_create")}?model={self.model.pk}')
        self.assertNotContains(response, 'name="vehicle_model"')
        self.assertNotContains(response, 'name="reward_items-TOTAL_FORMS"')
        self.assertNotContains(response, "批次套用到多個年式")

    def test_commission_save_does_not_change_reward_campaign(self):
        campaign = self.make_campaign(("physical", "機油", 1, "瓶"))
        response = self.client.post(self.url, {
            "action": "save_commission", "base_dealer_commission": "1800"
        })
        self.assertRedirects(response, f"{self.url}#cash-commission")
        self.model.refresh_from_db()
        self.assertEqual(self.model.base_dealer_commission, Decimal("1800"))
        self.assertEqual(campaign.items.get().name, "機油")

    def test_vehicle_page_shows_current_reward_summary_and_compact_toggle(self):
        self.make_campaign(("cash_gift", "紅包", 1000, "元"))
        # 摘要卡已改為機種工作區分頁：規格頁提供分頁入口，獎勵摘要在「傭金與獎勵」分頁。
        response = self.client.get(reverse("vehicle_model_edit", args=[self.model.pk]))
        self.assertContains(response, reverse("vehicle_model_commission", args=[self.model.pk]))
        response = self.client.get(reverse("vehicle_model_commission", args=[self.model.pk]))
        self.assertContains(response, "車行傭金與銷售獎勵")
        self.assertContains(response, "紅包 1000 元")
        listing = self.client.get(reverse("vehicle_model_list"))
        self.assertContains(listing, "vehicle-model-active-toggle")
        self.assertNotContains(listing, "vehicle-model-status--active")

    def test_program_directory_is_a_first_class_searchable_entry(self):
        self.make_campaign(("physical", "全合成機油", 2, "瓶"))
        other_model = VehicleModel.objects.create(
            brand="SYM",
            name="沒有獎勵的車型",
            model_number="NO-REWARD",
            model_year=2025,
            model_code=VehicleModel.ModelType.DRUM,
            energy_type=VehicleModel.EnergyType.GAS,
            displacement_cc=125,
        )
        inactive_model = VehicleModel.objects.create(
            brand="SUZUKI",
            name="歷史停用車型",
            model_number="INACTIVE",
            model_year=2024,
            model_code=VehicleModel.ModelType.DISC,
            energy_type=VehicleModel.EnergyType.GAS,
            displacement_cc=125,
            active=False,
        )
        url = reverse("dealer_sales_program_list")

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "車行傭金與銷售獎勵")
        self.assertContains(response, "全合成機油 2 瓶")
        self.assertContains(response, reverse("vehicle_model_commission", args=[self.model.pk]))
        self.assertContains(response, reverse("vehicle_model_commission", args=[other_model.pk]))
        self.assertNotContains(response, "歷史停用車型")
        self.assertContains(response, "啟用中車型")
        self.assertContains(response, "已停用車型")
        self.assertNotContains(response, "全部狀態")

        filtered = self.client.get(url, {"brand": "SUZUKI", "reward": "yes"})
        self.assertContains(filtered, "獎勵測試車")
        self.assertNotContains(filtered, "沒有獎勵的車型")

        inactive = self.client.get(url, {"status": "inactive"})
        self.assertContains(inactive, "歷史停用車型")
        self.assertNotContains(inactive, "獎勵測試車")
        self.assertContains(
            inactive,
            reverse("vehicle_model_commission", args=[inactive_model.pk]),
        )

        preserved = self.client.get(url, {"status": "active", "brand": "SUZUKI"})
        self.assertContains(preserved, "?status=inactive&amp;brand=SUZUKI")

    def test_program_directory_is_exposed_from_maintenance_and_mobile_shortcuts(self):
        route = reverse("dealer_sales_program_list")
        maintenance = self.client.get(reverse("data_maintenance"))
        self.assertContains(maintenance, route)
        self.assertContains(maintenance, "車行傭金與獎勵")

        dashboard = self.client.get(reverse("dashboard"))
        self.assertContains(dashboard, "車行傭金與銷售獎勵")
        self.assertContains(dashboard, 'value="dealer-sales-programs"')
