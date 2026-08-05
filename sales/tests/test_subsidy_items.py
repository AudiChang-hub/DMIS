from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import (
    OrderOperationsProfile,
    SalesOrder,
    SubsidyItem,
    VehicleColor,
    VehicleModel,
)


class SubsidyItemTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="subsidy-tester", password="test-pass-123"
        )
        vehicle_model = VehicleModel.objects.create(
            brand="測試牌",
            name="補助車",
            energy_type=VehicleModel.EnergyType.ELECTRIC,
        )
        color = VehicleColor.objects.create(vehicle_model=vehicle_model, name="白")
        self.order = SalesOrder.objects.create(
            owner_type=SalesOrder.OwnerType.COMPANY,
            owner_name="測試有限公司",
            owner_phone="0912345678",
            owner_address="新北市",
            owner_id_number="12345678",
            vehicle_model=vehicle_model,
            color=color,
            id_verified=True,
        )
        self.client.force_login(self.user)

    def _base_post(self):
        return {
            "_order_revision": str(self.order.revision),
            "is_trade_in_subsidy": "on",
            "old_owner_same_as_owner": "on",
            "trade_in_plate": "ABC-1234",
            "old_owner_name": "",
            "old_owner_id_number": "",
            "subsidy_type": "汰舊換新",
            "old_vehicle_valuation": "0",
            "old_vehicle_tax": "0",
            "change_reason": "新增補助申請項目",
            "subsidy_items-TOTAL_FORMS": "1",
            "subsidy_items-INITIAL_FORMS": "0",
            "subsidy_items-MIN_NUM_FORMS": "0",
            "subsidy_items-MAX_NUM_FORMS": "1000",
            "subsidy_items-0-category": SubsidyItem.Category.LOCAL,
            "subsidy_items-0-item_name": "地方汰舊補助",
            "subsidy_items-0-expected_amount": "5000",
            "subsidy_items-0-applied_on": "2026-08-05",
            "subsidy_items-0-status": SubsidyItem.Status.SUBMITTED,
            "subsidy_items-0-note": "已送件",
        }

    def test_subsidy_items_sync_aggregate_to_operations_profile(self):
        response = self.client.post(
            reverse("subsidy_data_update", args=[self.order.pk]), self._base_post()
        )

        self.assertRedirects(
            response,
            f"{reverse('order_detail', args=[self.order.pk])}?tab=subsidy",
        )
        item = self.order.subsidy_items.get()
        self.assertEqual(item.expected_amount, Decimal("5000"))
        profile = OrderOperationsProfile.objects.get(order=self.order)
        self.assertEqual(profile.subsidy_amount, Decimal("5000"))
        self.assertEqual(profile.subsidy_applied_on, date(2026, 8, 5))

    def test_deleting_all_items_clears_operations_aggregate(self):
        item = SubsidyItem.objects.create(
            order=self.order,
            category=SubsidyItem.Category.ENVIRONMENT,
            item_name="環境部補助",
            expected_amount=3000,
            applied_on=date(2026, 8, 4),
        )
        OrderOperationsProfile.objects.filter(order=self.order).update(
            subsidy_amount=3000, subsidy_applied_on=date(2026, 8, 4)
        )
        post = self._base_post()
        post.update(
            {
                "subsidy_items-INITIAL_FORMS": "1",
                "subsidy_items-0-id": str(item.pk),
                "subsidy_items-0-DELETE": "on",
            }
        )

        self.client.post(reverse("subsidy_data_update", args=[self.order.pk]), post)

        self.assertFalse(self.order.subsidy_items.exists())
        profile = OrderOperationsProfile.objects.get(order=self.order)
        self.assertEqual(profile.subsidy_amount, Decimal("0"))
        self.assertIsNone(profile.subsidy_applied_on)
