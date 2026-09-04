from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import (
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

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("vehicle_model_commission", args=[self.model.pk])

    def reward_payload(self, *, start="2026-09-01", items=None, **overrides):
        items = items or [
            ("physical", "全合成機油", "2", "瓶", ""),
            ("travel_points", "國內旅遊", "1", "", "逐台累積"),
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
        for index, (kind, name, quantity, unit, note) in enumerate(items):
            data.update({
                f"reward_items-{index}-reward_type": kind,
                f"reward_items-{index}-name": name,
                f"reward_items-{index}-quantity": quantity,
                f"reward_items-{index}-unit": unit,
                f"reward_items-{index}-note": note,
            })
        data.update(overrides)
        return data

    def test_page_is_bound_to_vehicle_and_separates_commission_from_rewards(self):
        response = self.client.get(self.url)
        self.assertContains(response, "車行方案")
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
        self.model.refresh_from_db()
        self.assertEqual(self.model.base_dealer_commission, Decimal("1200"))

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
            self.reward_payload(start="2026-09-15", items=[("voucher", "禮券", "500", "元", "")]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "此期間已有啟用中的車行附加獎勵")
        self.assertEqual(DealerVehicleRewardPlan.objects.count(), 1)

    def test_duplicate_or_empty_items_are_rejected_atomically(self):
        duplicate = [("physical", "機油", "1", "瓶", ""), ("physical", "機油", "2", "瓶", "")]
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
        self.assertContains(response, "車行方案")
        self.assertContains(response, "紅包 1000 元")
        listing = self.client.get(reverse("vehicle_model_list"))
        self.assertContains(listing, "vehicle-model-active-toggle")
        self.assertNotContains(listing, "vehicle-model-status--active")
