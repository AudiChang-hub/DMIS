from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse

from sales.services.order_steps import order_step_url
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
            order_step_url(self.order.pk, "subsidy"),
        )
        item = self.order.subsidy_items.get()
        self.assertEqual(item.expected_amount, Decimal("5000"))
        profile = OrderOperationsProfile.objects.get(order=self.order)
        self.assertEqual(profile.subsidy_amount, Decimal("5000"))
        self.assertEqual(profile.subsidy_applied_on, date(2026, 8, 5))

    def test_name_and_amount_are_enough_and_several_items_can_be_added(self):
        post = self._base_post()
        for key in [key for key in post if key.startswith("subsidy_items-0-")]:
            del post[key]
        post.update({
            "subsidy_items-TOTAL_FORMS": "2",
            "subsidy_items-0-item_name": "工業局購車補助",
            "subsidy_items-0-expected_amount": "8000",
            "subsidy_items-0-status": SubsidyItem.Status.NOT_SUBMITTED,  # 下拉預設值，瀏覽器一定會送
            "subsidy_items-1-item_name": "新北新購補助",
            "subsidy_items-1-expected_amount": "12000",
            "subsidy_items-1-status": SubsidyItem.Status.NOT_SUBMITTED,
        })
        response = self.client.post(reverse("subsidy_data_update", args=[self.order.pk]), post)
        self.assertRedirects(response, order_step_url(self.order.pk, "subsidy"))
        items = list(self.order.subsidy_items.order_by("id"))
        self.assertEqual([item.item_name for item in items], ["工業局購車補助", "新北新購補助"])
        self.assertEqual({item.category for item in items}, {SubsidyItem.Category.OTHER})
        self.assertEqual(OrderOperationsProfile.objects.get(order=self.order).subsidy_amount, Decimal("20000"))

    def test_past_names_are_suggested_most_used_first(self):
        def add(order, name):
            SubsidyItem.objects.create(order=order, category=SubsidyItem.Category.OTHER, item_name=name, expected_amount=1)
        other = SalesOrder.objects.create(
            owner_name="另一位", owner_phone="0922", owner_address="新北市", owner_id_number="A1",
            vehicle_model=self.order.vehicle_model, color=self.order.color,
        )
        add(self.order, "環境部汰舊補助")
        add(other, "環境部汰舊補助")
        add(other, "工業局購車補助")
        gone = SalesOrder.objects.create(
            owner_name="已刪除", owner_phone="0933", owner_address="新北市", owner_id_number="A2",
            vehicle_model=self.order.vehicle_model, color=self.order.color,
        )
        add(gone, "已刪除訂單的補助")
        SalesOrder.all_objects.filter(pk=gone.pk).update(deleted_at=timezone.now())
        from sales.services.subsidy_names import subsidy_name_suggestions
        self.assertEqual(subsidy_name_suggestions(), ["環境部汰舊補助", "工業局購車補助"])
        page = self.client.get(order_step_url(self.order.pk, "subsidy"))
        self.assertContains(page, '<datalist id="subsidy-name-suggestions">')
        self.assertContains(page, '<option value="環境部汰舊補助">')
        self.assertNotContains(page, "已刪除訂單的補助")
        self.assertContains(page, 'list="subsidy-name-suggestions"')

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
