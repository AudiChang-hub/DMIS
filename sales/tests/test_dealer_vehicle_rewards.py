from datetime import date
from decimal import Decimal
from pathlib import Path

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

    def reward_payload(self, *, start="2026-09-01", items=None, **overrides):
        items = items or [
            (self.physical_item, "2", ""),
            (self.travel_item, "1", "逐台累積"),
        ]
        data = {
            "action": "save_rewards",
            "new_reward": "1",
            "reward_id": "",
            "effective_from": start,
            "effective_to": "",
            "active": "on",
            "note": "九月方案",
            "reward_items-TOTAL_FORMS": str(len(items)),
            "reward_items-INITIAL_FORMS": "0",
            "reward_items-MIN_NUM_FORMS": "1",
            "reward_items-MAX_NUM_FORMS": "1000",
        }
        for index, (catalog_item, quantity, note) in enumerate(items):
            data.update({
                f"reward_items-{index}-catalog_item": str(catalog_item.pk),
                f"reward_items-{index}-quantity": quantity,
                f"reward_items-{index}-note": note,
            })
        data.update(overrides)
        return data

    def test_page_is_bound_to_vehicle_and_separates_commission_from_rewards(self):
        response = self.client.get(self.url)
        self.assertContains(response, "車行傭金與銷售獎勵")
        self.assertContains(response, "車型由系統帶入，不需重選")
        self.assertContains(response, "車行基礎傭金")
        self.assertContains(response, "車行附加獎勵")
        self.assertNotContains(response, 'name="vehicle_model"')

    def test_multiple_reward_items_save_without_changing_commission(self):
        response = self.client.post(self.url, self.reward_payload())
        plan = DealerVehicleRewardPlan.objects.get()
        self.assertRedirects(response, f"{self.url}?reward={plan.pk}#dealer-rewards")
        self.assertEqual(plan.vehicle_model_id, self.model.pk)
        self.assertEqual(plan.items.count(), 2)
        self.assertEqual(plan.items.get(reward_type="physical").display_label, "全合成機油 2 瓶")
        self.assertEqual(plan.items.get(reward_type="travel_points").unit, "點")
        self.assertEqual(
            plan.items.get(reward_type="physical").unit_cost_snapshot,
            Decimal("180"),
        )
        self.assertEqual(
            plan.items.get(reward_type="physical").total_cost_snapshot,
            Decimal("360"),
        )
        self.model.refresh_from_db()
        self.assertEqual(self.model.base_dealer_commission, Decimal("1200"))

    def test_cost_snapshot_is_stable_until_catalog_or_effective_date_changes(self):
        response = self.client.post(
            self.url,
            self.reward_payload(items=[(self.physical_item, "2", "")]),
        )
        plan = DealerVehicleRewardPlan.objects.get()
        reward = plan.items.get()
        self.assertRedirects(response, f"{self.url}?reward={plan.pk}#dealer-rewards")
        self.assertEqual(reward.unit_cost_snapshot, Decimal("180"))

        first_cost = self.physical_item.cost_versions.get()
        first_cost.effective_to = date(2026, 9, 30)
        first_cost.save()
        DealerRewardCostVersion.objects.create(
            catalog_item=self.physical_item,
            effective_from=date(2026, 10, 1),
            unit_cost=220,
        )
        edit_payload = self.reward_payload(
            items=[(self.physical_item, "2", "只改說明")],
            reward_id=str(plan.pk),
            new_reward="",
            **{
                "reward_items-INITIAL_FORMS": "1",
                "reward_items-0-id": str(reward.pk),
            },
        )
        self.client.post(self.url, edit_payload)
        reward.refresh_from_db()
        self.assertEqual(reward.unit_cost_snapshot, Decimal("180"))

        edit_payload["effective_from"] = "2026-10-01"
        self.client.post(self.url, edit_payload)
        reward.refresh_from_db()
        self.assertEqual(reward.unit_cost_snapshot, Decimal("220"))
        self.assertEqual(reward.cost_effective_on_snapshot, date(2026, 10, 1))

    def test_reward_page_uses_catalog_select_and_cost_preview(self):
        response = self.client.get(self.url)

        self.assertContains(response, 'data-reward-catalog=""')
        self.assertContains(response, "全合成機油 · 實物／瓶")
        self.assertContains(response, "單位成本快照")
        self.assertContains(response, reverse("dealer_reward_catalog_list"))

    def test_reward_editor_uses_grouped_responsive_layout(self):
        response = self.client.get(self.url)
        content = response.content.decode()

        self.assertContains(response, 'class="dealer-reward-settings"')
        self.assertContains(response, 'class="dealer-reward-enabled-toggle"')
        self.assertContains(response, 'class="dealer-reward-item__fields"')
        self.assertContains(response, 'class="dealer-reward-item__note"')
        self.assertNotContains(response, "返回方案總覽")
        self.assertEqual(content.count("儲存附加獎勵"), 1)

        css = (Path(__file__).resolve().parents[2] / "static" / "css" / "app.css").read_text(
            encoding="utf-8"
        )
        self.assertIn(".dealer-reward-item__fields {", css)
        self.assertIn("align-items: start", css)
        self.assertNotIn(
            "grid-template-columns: 1fr 1.4fr .8fr .7fr 1.4fr auto",
            css,
        )

    def test_commission_save_does_not_change_reward_plan(self):
        plan = DealerVehicleRewardPlan.objects.create(
            vehicle_model=self.model, effective_from=date(2026, 9, 1)
        )
        DealerVehicleRewardItem.objects.create(
            plan=plan, reward_type="physical", name="機油", quantity=1, unit="瓶"
        )
        response = self.client.post(self.url, {
            "action": "save_commission", "base_dealer_commission": "1800"
        })
        self.assertRedirects(response, f"{self.url}#cash-commission")
        self.model.refresh_from_db()
        self.assertEqual(self.model.base_dealer_commission, Decimal("1800"))
        self.assertEqual(plan.items.get().name, "機油")

    def test_overlapping_active_versions_are_rejected(self):
        first = DealerVehicleRewardPlan.objects.create(
            vehicle_model=self.model,
            effective_from=date(2026, 9, 1),
            effective_to=date(2026, 9, 30),
        )
        DealerVehicleRewardItem.objects.create(
            plan=first, reward_type="physical", name="機油", quantity=1
        )
        response = self.client.post(
            self.url,
            self.reward_payload(start="2026-09-15", items=[(self.voucher_item, "1", "")]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "此期間已有啟用中的車行附加獎勵")
        self.assertEqual(DealerVehicleRewardPlan.objects.count(), 1)

    def test_duplicate_or_empty_items_are_rejected_atomically(self):
        duplicate = [(self.physical_item, "1", ""), (self.physical_item, "2", "")]
        response = self.client.post(self.url, self.reward_payload(items=duplicate))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "同一方案不可重複填寫相同獎勵")
        self.assertFalse(DealerVehicleRewardPlan.objects.exists())

    def test_vehicle_page_shows_current_reward_summary_and_compact_toggle(self):
        plan = DealerVehicleRewardPlan.objects.create(
            vehicle_model=self.model, effective_from=date(2026, 9, 1)
        )
        DealerVehicleRewardItem.objects.create(
            plan=plan, reward_type="cash_gift", name="紅包", quantity=1000
        )
        response = self.client.get(reverse("vehicle_model_edit", args=[self.model.pk]))
        self.assertContains(response, "車行傭金與銷售獎勵")
        self.assertContains(response, "紅包 1000 元")
        listing = self.client.get(reverse("vehicle_model_list"))
        self.assertContains(listing, "vehicle-model-active-toggle")
        self.assertNotContains(listing, "vehicle-model-status--active")

    def test_program_directory_is_a_first_class_searchable_entry(self):
        plan = DealerVehicleRewardPlan.objects.create(
            vehicle_model=self.model, effective_from=date(2026, 9, 1)
        )
        DealerVehicleRewardItem.objects.create(
            plan=plan, reward_type="physical", name="全合成機油", quantity=2, unit="瓶"
        )
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
        self.assertContains(maintenance, "逐台給付的現金傭金")

        dashboard = self.client.get(reverse("dashboard"))
        self.assertContains(dashboard, "車行傭金與銷售獎勵")
        self.assertContains(dashboard, 'value="dealer-sales-programs"')
