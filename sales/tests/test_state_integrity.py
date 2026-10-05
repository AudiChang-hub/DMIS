from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.forms import AllocationForm, VehicleInventoryForm
from sales.models import OrderEvent, PaymentRecord, SalesOrder, VehicleInventory, VehicleInventoryHistory
from sales.services.order_next_actions import build_order_next_actions
from sales.services.sales_metrics import filter_payment_risk
from sales.tests import test_order_lifecycle as lifecycle


class StateIntegrityTests(TestCase):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order
    delivery_payload = lifecycle.OrderLifecycleTests.delivery_payload
    confirm_deposit = lifecycle.OrderLifecycleTests.confirm_deposit

    def vehicle(self, tag, made=""):
        return VehicleInventory.objects.create(
            vehicle_model=self.model, color=self.color, engine_number=f"SI-{tag}", manufactured_year_month=made,
            ownership_store=self.store, location_store=self.store,
        )

    def pending_order(self):
        order, vehicle = self.make_order(deposit=Decimal("0"))
        order.request_cancellation("測試", "只取待配車狀態")
        SalesOrder.objects.filter(pk=order.pk).update(status=SalesOrder.Status.ALLOCATION_PENDING,
                                                      accepted_at=timezone.now())
        order.refresh_from_db()
        return order

    # M7：庫存異動全程留痕
    def test_allocation_reallocation_cancel_and_delivery_write_inventory_history(self):
        order, first = self.make_order(dealer=True, deposit=Decimal("0"))
        self.assertIsNotNone(order.allocated_at)
        self.assertTrue(VehicleInventoryHistory.objects.filter(vehicle=first, reason__contains="配給訂單").exists())
        second = self.vehicle("R2")
        order.reallocate(second, actor_name="測試", reason="原車刮傷")
        self.assertTrue(VehicleInventoryHistory.objects.filter(vehicle=first, reason__contains="釋回此車").exists())
        self.assertTrue(VehicleInventoryHistory.objects.filter(vehicle=second, reason__contains="改配為此車；原因：原車刮傷").exists())
        order.refresh_from_db()
        order.complete_delivery(timezone.now(), "測試")
        self.assertEqual(VehicleInventoryHistory.objects.filter(vehicle=second, reason__contains="完成交付").count(), 1)

    # 集中狀態轉移
    def test_transition_table_rejects_illegal_moves(self):
        order, _vehicle = self.make_order()
        order.ensure_transition(SalesOrder.Status.DELIVERY_PENDING)
        with self.assertRaisesMessage(ValidationError, "不能轉為"):
            order.ensure_transition(SalesOrder.Status.INTAKE_PENDING)
        completed = SalesOrder(status=SalesOrder.Status.COMPLETED)
        with self.assertRaises(ValidationError):
            completed.ensure_transition(SalesOrder.Status.CANCELLED)

    # M5：排隊順序與先進先出
    def test_allocation_queue_and_fifo_require_reason(self):
        first_order = self.pending_order()
        second_order = self.pending_order()
        SalesOrder.objects.filter(pk=second_order.pk).update(accepted_at=timezone.now() + timedelta(minutes=5))
        second_order.refresh_from_db()
        # 兩台都未滿優先配車門檻（相對今天），驗證同級先進先出仍強制填原因；跳過優先配車見 test_allocation_priority。
        today = timezone.localdate()
        older_index, newer_index = today.year * 12 + today.month - 3, today.year * 12 + today.month - 2
        old = self.vehicle("OLD", f"{older_index // 12:04d}/{older_index % 12 + 1:02d}")
        new = self.vehicle("NEW", f"{newer_index // 12:04d}/{newer_index % 12 + 1:02d}")
        form = AllocationForm(second_order, {"vehicle": old.pk})
        self.assertEqual(form.queue_position, 2)
        self.assertFalse(form.is_valid())
        self.assertIn("skip_reason", form.errors)
        form = AllocationForm(first_order, {"vehicle": new.pk})
        self.assertEqual(form.queue_position, 1)
        self.assertFalse(form.is_valid())
        self.assertIn("較早出廠", str(form.errors))
        self.assertTrue(AllocationForm(first_order, {"vehicle": old.pk}).is_valid())
        self.client.force_login(self.user)
        self.client.post(reverse("allocate_vehicle", args=[second_order.pk]), {"vehicle": old.pk, "skip_reason": "客戶先付清"})
        second_order.refresh_from_db()
        self.assertEqual(second_order.allocated_vehicle_id, old.pk)
        self.assertEqual(second_order.allocation_skip_reason, "客戶先付清")
        self.assertIn("客戶先付清", OrderEvent.objects.filter(order=second_order, event_type="allocated").get().description)

    def test_stale_allocation_is_flagged(self):
        order, _vehicle = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(allocated_at=timezone.now() - timedelta(days=45))
        order.refresh_from_db()
        self.assertTrue(filter_payment_risk(SalesOrder.objects.filter(pk=order.pk), "stale_allocation").exists())
        actions = build_order_next_actions(order)
        self.assertIn("stale-allocation", [action.key for action in actions.all_actions])

    # L3：撤銷取消
    def test_withdraw_cancellation_returns_to_allocation_pending(self):
        order, vehicle = self.make_order()
        self.confirm_deposit(order)
        order.request_cancellation("測試", "客戶考慮")
        SalesOrder.objects.filter(pk=order.pk).update(accepted_at=timezone.now())
        order.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, "撤銷原因"):
            order.withdraw_cancellation("測試", " ")
        order.withdraw_cancellation("測試", "客戶決定照買")
        order.refresh_from_db()
        vehicle.refresh_from_db()
        self.assertEqual(order.status, SalesOrder.Status.ALLOCATION_PENDING)
        self.assertEqual(order.cancellation_reason, "")
        self.assertEqual(vehicle.status, VehicleInventory.Status.AVAILABLE)
        self.assertTrue(OrderEvent.objects.filter(order=order, event_type="cancellation_withdrawn").exists())
        with self.assertRaises(ValidationError):
            order.withdraw_cancellation("測試", "再撤一次")

    # M6：車況異常可實際使用並阻擋配車
    def test_condition_hold_blocks_allocation(self):
        vehicle = self.vehicle("HOLD")
        data = {"vehicle_model": self.model.pk, "color": self.color.pk, "engine_number": "SI-HOLD",
                "received_on": "2026-08-01", "condition_hold": "on", "condition_note": ""}
        form = VehicleInventoryForm(data, instance=vehicle)
        self.assertFalse(form.is_valid())
        data["condition_note"] = "左側刮傷待修"
        form = VehicleInventoryForm(data, instance=vehicle)
        self.assertTrue(form.is_valid(), form.errors)
        vehicle = form.save()
        self.assertEqual(vehicle.status, VehicleInventory.Status.CONDITION_ISSUE)
        order = self.pending_order()
        with self.assertRaisesMessage(ValidationError, "不可配車"):
            order.allocate(vehicle)
        data.pop("condition_hold")
        vehicle = VehicleInventoryForm(data, instance=vehicle)
        self.assertTrue(vehicle.is_valid(), vehicle.errors)
        self.assertEqual(vehicle.save().status, VehicleInventory.Status.AVAILABLE)

    # L4：訂單編號撞號重取
    def test_order_number_collision_retries(self):
        order, _vehicle = self.make_order()
        taken = order.number.split("-")[1]
        fresh = "ABCDEF0000000000000000000000000A"
        with patch("sales.models.uuid.uuid4") as fake:
            fake.side_effect = [type("U", (), {"hex": taken.lower() + "0" * 26})(), type("U", (), {"hex": fresh})()]
            again, _vehicle = self.make_order()
        self.assertNotEqual(again.number, order.number)
        self.assertTrue(again.number.endswith("ABCDEF"))
