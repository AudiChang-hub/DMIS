import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import (
    PaymentRecord,
    SalesOrder,
    SalesSource,
    Store,
    VehicleColor,
    VehicleInventory,
    VehicleModel,
)
from sales.services.order_next_actions import build_order_next_actions


class OrderNextActionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="next-action-user",
            password="test-pass-123",
        )
        self.store = Store.objects.create(name="總店", code="HQ")
        self.model = VehicleModel.objects.create(
            brand="SUZUKI",
            name="SUI 125",
            energy_type=VehicleModel.EnergyType.GAS,
        )
        self.color = VehicleColor.objects.create(
            vehicle_model=self.model,
            name="灰",
        )
        self.dealer = SalesSource.objects.create(
            name="合作車行甲",
            source_type=SalesSource.SourceType.DEALER,
        )
        self.platform = SalesSource.objects.create(
            name="網路平台甲",
            source_type=SalesSource.SourceType.PLATFORM,
        )
        self.vehicle_sequence = 0

    def make_order(self, *, source_type=SalesOrder.SourceType.STORE, subsidy=False, payment_type=SalesOrder.PaymentType.CASH):
        source = None
        if source_type == SalesOrder.SourceType.DEALER:
            source = self.dealer
        elif source_type == SalesOrder.SourceType.PLATFORM:
            source = self.platform
        values = {
            "owner_name": "王小明",
            "owner_phone": "0912345678",
            "owner_address": "新北市測試區",
            "owner_id_number": "A123456789",
            "vehicle_model": self.model,
            "color": self.color,
            "source_type": source_type,
            "source": source,
            "payment_type": payment_type,
            "vehicle_price": Decimal("70000"),
            "actual_balance": Decimal("70000"),
            "id_verified": True,
            "is_trade_in_subsidy": subsidy,
            "old_owner_same_as_owner": True,
            "trade_in_plate": "ABC-1234" if subsidy else "",
            "subsidy_type": "汰舊換新" if subsidy else "",
        }
        if payment_type == SalesOrder.PaymentType.INSTALLMENT:
            values.update(
                {
                    "installment_company": "測試分期",
                    "installment_amount": Decimal("60000"),
                    "installment_periods": 24,
                    "installment_monthly": Decimal("3000"),
                }
            )
        return SalesOrder.objects.create(**values)

    def make_vehicle(self, *, status=VehicleInventory.Status.AVAILABLE):
        self.vehicle_sequence += 1
        return VehicleInventory.objects.create(
            vehicle_model=self.model,
            color=self.color,
            engine_number=f"NEXT-{self.vehicle_sequence:03d}",
            ownership_store=self.store,
            location_store=self.store,
            status=status,
        )

    def build(self, order, *, today=date(2026, 8, 10), registration_missing=None, subsidy_missing=None):
        order = SalesOrder.objects.select_related(
            "vehicle_model",
            "color",
            "allocated_vehicle",
        ).prefetch_related("payment_records", "subsidy_items").get(pk=order.pk)
        return build_order_next_actions(
            order,
            today=today,
            registration_missing=registration_missing,
            subsidy_missing=subsidy_missing,
        )

    def test_unallocated_order_distinguishes_available_inventory(self):
        order = self.make_order()

        no_inventory = self.build(order)
        self.assertEqual(no_inventory.primary.key, "inventory-entry")
        self.assertEqual(no_inventory.primary.url, reverse("inventory_quick_create"))

        self.make_vehicle()
        available = self.build(order)
        self.assertEqual(available.primary.key, "allocation")
        self.assertEqual(
            available.primary.url,
            f"{reverse('order_detail', args=[order.pk])}?tab=allocation",
        )

    def test_subsidy_is_parallel_and_actions_are_limited(self):
        order = self.make_order(subsidy=True)
        self.make_vehicle()

        actions = self.build(order)

        self.assertEqual(actions.primary.key, "allocation")
        self.assertIn("subsidy", [action.key for action in actions.secondary])
        self.assertLessEqual(len(actions.secondary), 2)
        self.assertEqual(len({action.key for action in actions.all_actions}), len(actions.all_actions))

    def test_store_order_requires_registration_before_delivery(self):
        order = self.make_order()
        order.allocate(self.make_vehicle())

        actions = self.build(order)

        self.assertEqual(actions.primary.key, "registration")
        self.assertNotIn("dealer-early-delivery", [action.key for action in actions.secondary])

    def test_dealer_can_see_early_delivery_as_parallel_action(self):
        order = self.make_order(source_type=SalesOrder.SourceType.DEALER)
        order.allocate(self.make_vehicle())

        actions = self.build(order)

        self.assertEqual(actions.primary.key, "registration")
        self.assertEqual(actions.secondary[0].key, "dealer-early-delivery")
        self.assertIn("?tab=delivery", actions.secondary[0].url)

    def test_transfer_and_condition_issues_take_priority(self):
        for status, expected_key in (
            (VehicleInventory.Status.IN_TRANSFER, "vehicle-transfer"),
            (VehicleInventory.Status.CONDITION_ISSUE, "vehicle-condition"),
        ):
            with self.subTest(status=status):
                order = self.make_order()
                vehicle = self.make_vehicle()
                order.allocate(vehicle)
                VehicleInventory.objects.filter(pk=vehicle.pk).update(status=status)

                actions = self.build(order)

                self.assertEqual(actions.primary.key, expected_key)

    def test_registration_without_cost_rule_points_to_cost_maintenance(self):
        order = self.make_order()
        order.allocate(self.make_vehicle())
        SalesOrder.objects.filter(pk=order.pk).update(
            registration_date=date(2026, 8, 10),
            registration_county="新北市",
            final_plate_number="ABC-1234",
        )

        actions = self.build(order, registration_missing=[])

        self.assertEqual(actions.primary.key, "settlement-cost")
        self.assertIn(reverse("settlement_cost_rule_list"), actions.primary.url)

    def test_registered_order_points_to_delivery(self):
        order = self.make_order()
        order.allocate(self.make_vehicle())
        SalesOrder.objects.filter(pk=order.pk).update(
            registration_completed_at=timezone.now(),
            status=SalesOrder.Status.DELIVERY_PENDING,
        )

        actions = self.build(order)

        self.assertEqual(actions.primary.key, "delivery")
        self.assertIn("?tab=delivery", actions.primary.url)
        self.assertEqual(actions.primary.target_tab, "delivery")

    def test_delivery_tab_marks_delivery_recommendation_as_current_work(self):
        order = self.make_order()
        order.allocate(self.make_vehicle())
        SalesOrder.objects.filter(pk=order.pk).update(
            registration_completed_at=timezone.now(),
            status=SalesOrder.Status.DELIVERY_PENDING,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            f"{reverse('order_detail', args=[order.pk])}?tab=delivery"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_tab"], "delivery")
        self.assertContains(response, "next-actions--primary is-current-context")
        self.assertContains(response, 'data-current-tab="delivery"')
        self.assertContains(response, 'data-target-tab="delivery"')
        self.assertContains(response, "data-next-actions-controls hidden")
        self.assertContains(response, ">目前作業<")

    def test_other_tab_keeps_delivery_navigation_available(self):
        order = self.make_order()
        order.allocate(self.make_vehicle())
        SalesOrder.objects.filter(pk=order.pk).update(
            registration_completed_at=timezone.now(),
            status=SalesOrder.Status.DELIVERY_PENDING,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            f"{reverse('order_detail', args=[order.pk])}?tab=order"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_tab"], "order")
        self.assertContains(response, 'data-current-tab="order"')
        self.assertNotContains(response, "next-actions--primary is-current-context")
        self.assertNotContains(response, "data-next-actions-controls hidden")
        self.assertContains(response, "前往交付")

    def test_current_secondary_tab_is_presented_as_non_navigation(self):
        order = self.make_order(source_type=SalesOrder.SourceType.DEALER)
        order.allocate(self.make_vehicle())
        self.client.force_login(self.user)

        response = self.client.get(
            f"{reverse('order_detail', args=[order.pk])}?tab=delivery"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'data-action-key="dealer-early-delivery" data-target-tab="delivery"',
        )
        self.assertContains(response, ">目前頁面<")
        action_markup = re.search(
            r'<a(?=[^>]*data-action-key="dealer-early-delivery")[^>]*>',
            response.content.decode("utf-8"),
        ).group(0)
        self.assertNotIn(" href=", action_markup)
        self.assertIn('aria-current="location"', action_markup)
        self.assertIn('tabindex="-1"', action_markup)

    def test_invalid_tab_falls_back_without_hiding_delivery_navigation(self):
        order = self.make_order()
        order.allocate(self.make_vehicle())
        SalesOrder.objects.filter(pk=order.pk).update(
            registration_completed_at=timezone.now(),
            status=SalesOrder.Status.DELIVERY_PENDING,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            f"{reverse('order_detail', args=[order.pk])}?tab=not-a-real-tab"
        )

        self.assertEqual(response.context["active_tab"], "order")
        self.assertNotContains(response, "data-next-actions-controls hidden")
        self.assertContains(response, "前往交付")

    def test_dealer_delivered_before_registration_has_both_deadlines(self):
        order = self.make_order(source_type=SalesOrder.SourceType.DEALER)
        vehicle = self.make_vehicle()
        order.allocate(vehicle)
        delivered_at = timezone.make_aware(datetime(2026, 8, 3, 10, 0))
        SalesOrder.objects.filter(pk=order.pk).update(
            status=SalesOrder.Status.DELIVERED_DOCS_PENDING,
            delivered_at=delivered_at,
        )
        VehicleInventory.objects.filter(pk=vehicle.pk).update(
            status=VehicleInventory.Status.DELIVERED
        )

        actions = self.build(order)

        self.assertEqual(actions.primary.key, "registration")
        self.assertEqual(actions.primary.tone, "urgent")
        self.assertIn("2026/08/06", actions.primary.description)
        reconciliation = next(
            action for action in actions.secondary if action.key == "reconciliation"
        )
        self.assertIn("2026/08/12", reconciliation.description)

    def test_refund_pending_suppresses_every_other_action_and_cancelled_is_quiet(self):
        order = self.make_order(subsidy=True)
        SalesOrder.objects.filter(pk=order.pk).update(
            status=SalesOrder.Status.CANCEL_REFUND_PENDING
        )

        refund = self.build(order)
        self.assertEqual(refund.primary.key, "refund")
        self.assertEqual(refund.secondary, ())

        SalesOrder.objects.filter(pk=order.pk).update(status=SalesOrder.Status.CANCELLED)
        self.assertIsNone(self.build(order))

    def test_only_supported_channels_enter_unified_reconciliation(self):
        store_cash = self.make_order()
        dealer_cash = self.make_order(source_type=SalesOrder.SourceType.DEALER)
        store_installment = self.make_order(payment_type=SalesOrder.PaymentType.INSTALLMENT)
        for order in (store_cash, dealer_cash, store_installment):
            SalesOrder.objects.filter(pk=order.pk).update(
                status=SalesOrder.Status.COMPLETED,
                delivered_at=timezone.now(),
                registration_completed_at=timezone.now(),
            )

        self.assertIsNone(self.build(store_cash))
        self.assertEqual(self.build(dealer_cash).primary.key, "reconciliation")
        self.assertEqual(self.build(store_installment).primary.key, "reconciliation")

        PaymentRecord.objects.filter(
            order=dealer_cash,
            system_key="balance",
        ).update(confirmed=True)
        self.assertIsNone(self.build(dealer_cash))

    def test_order_detail_renders_accessible_compact_workbar(self):
        order = self.make_order()
        self.make_vehicle()
        self.client.force_login(self.user)

        response = self.client.get(reverse("order_detail", args=[order.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context["next_actions"])
        self.assertContains(response, "data-next-actions")
        self.assertContains(response, "data-next-actions-workbar")
        self.assertContains(response, 'aria-labelledby="next-actions-title"')
        self.assertContains(response, 'aria-labelledby="next-actions-secondary-title"')
        self.assertContains(response, 'data-action-key="allocation"')
        self.assertContains(response, "另外可處理")
        self.assertContains(response, "收合")
        self.assertNotContains(response, ">稍後處理</button>")
        self.assertContains(response, "next-actions.js")
        self.assertNotContains(response, 'class="next-actions-dialog"')

    def test_dismissal_is_local_and_reopens_when_state_changes(self):
        script = Path("static/js/next-actions.js").read_text(encoding="utf-8")
        self.assertIn("const prefix = `order-next-actions:${orderId}:`", script)
        self.assertIn("const storageKey = `${prefix}${stateKey}`", script)
        self.assertIn("key.startsWith(prefix) && key !== storageKey", script)
        self.assertIn("data-next-actions-restore", script)
        self.assertIn('primary.dataset.targetTab === tabName', script)
        self.assertIn('controls.hidden = primaryIsCurrent', script)
        self.assertIn('action.removeAttribute("href")', script)
        self.assertIn('window.addEventListener("order-tab-change"', script)
        self.assertNotIn("window.location =", script)

        tab_script = Path("static/js/order-detail-tabs.js").read_text(encoding="utf-8")
        self.assertIn("tabList.dataset.activeTab = activeName", tab_script)
        self.assertIn('new CustomEvent("order-tab-change"', tab_script)

    def test_workbar_styles_do_not_split_secondary_actions_into_cards(self):
        styles = Path("static/css/app.css").read_text(encoding="utf-8")
        secondary_rule = styles.split(".next-actions__secondary {", 1)[1].split("}", 1)[0]

        self.assertIn("grid-template-columns: 116px minmax(0, 1fr)", secondary_rule)
        self.assertNotIn("repeat(2", secondary_rule)
        self.assertIn(".next-actions__secondary-list", styles)
