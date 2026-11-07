"""取消配車（使用者 2026-11-06 T-122 選 A＋B）。

A：配車步驟「取消配車」按鈕（前端先確認）。B：已配車時改車型／車色先警告，確認後同一交易內取消配車並存檔。
已交車、結案、取消或已開始領牌的單不能取消；車輛回到可銷售、訂單回到待配車，留 OrderEvent／OrderChange 與車輛歷程。
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from sales.models import OrderChange, OrderEvent, SalesOrder, VehicleColor, VehicleInventory, VehicleInventoryHistory
from sales.services.payment_summary import payment_summary
from sales.tests import test_order_lifecycle as lifecycle
from sales.tests.test_order_workspace import form_data, formset_data

RESERVED, AVAILABLE = VehicleInventory.Status.RESERVED, VehicleInventory.Status.AVAILABLE


class UnallocateTests(TestCase):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def test_button_unallocates_with_audit_and_vehicle_back_to_available(self):
        order, vehicle = self.make_order()
        before_summary = payment_summary(order)
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[order.pk]), {"step": "allocation"})
        self.assertContains(page, reverse("unallocate_vehicle", args=[order.pk]))
        self.assertContains(page, f"這張單已配車（{vehicle.identifier}）")
        response = self.client.post(reverse("unallocate_vehicle", args=[order.pk]))
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        vehicle.refresh_from_db()
        self.assertEqual((order.status, order.allocated_vehicle_id, order.allocated_at), (SalesOrder.Status.ALLOCATION_PENDING, None, None))
        self.assertEqual(vehicle.status, AVAILABLE)
        self.assertTrue(OrderEvent.objects.filter(order=order, event_type="unallocated").exists())
        self.assertEqual(OrderChange.objects.filter(order=order).latest("pk").changes["已配車輛"]["after"], "未配車")
        self.assertIn("取消配車", VehicleInventoryHistory.objects.filter(vehicle=vehicle).latest("pk").reason)
        after_summary = payment_summary(order)
        self.assertEqual((after_summary["customer_expected"], after_summary["customer_received"]),
                         (before_summary["customer_expected"], before_summary["customer_received"]), "收支不受影響")
        # 回到待配車後可以再配同一台車。
        order.allocate(vehicle)
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, RESERVED)

    def test_registration_started_or_delivered_cannot_unallocate(self):
        order, vehicle = self.make_order()
        order.final_plate_number = "ABC-1234"
        order.save(update_fields=["final_plate_number", "updated_at"])
        self.assertIn("已開始領牌", order.unallocation_blocker)
        with self.assertRaises(ValidationError):
            order.unallocate("測試人員")
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[order.pk]), {"step": "allocation"})
        self.assertContains(page, 'disabled aria-describedby="unallocate-blocker"', html=False)
        self.assertContains(page, "不能取消配車")
        self.client.post(reverse("unallocate_vehicle", args=[order.pk]))
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, RESERVED)
        SalesOrder.objects.filter(pk=order.pk).update(status=SalesOrder.Status.COMPLETED, final_plate_number="")
        order.refresh_from_db()
        self.assertIn("已交車", order.unallocation_blocker)

    def _edit(self, order, **changes):
        self.client.force_login(self.user)
        response = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "order"})
        data = {**form_data(response.context["form"]), **formset_data(response.context["formset"]),
                **formset_data(response.context["fee_formset"]), "_order_revision": order.revision, "_workspace": "1"}
        data.update(changes)
        return response, self.client.post(reverse("order_edit", args=[order.pk]), data, HTTP_X_ORDER_WORKSPACE="1")

    def test_changing_color_warns_and_needs_confirmation_then_unallocates(self):
        order, vehicle = self.make_order()
        other = VehicleColor.objects.create(vehicle_model=self.model, name="黑")
        page, response = self._edit(order, color=str(other.pk))
        self.assertContains(page, "data-unallocate-confirm")
        self.assertContains(page, f"這張單已經配了 {vehicle.identifier} 這台車，確定要換車嗎？")
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("換車色要先在確認視窗按「確定」換車", response.json()["errors"]["color"][0])
        order.refresh_from_db()
        self.assertEqual((order.color_id, order.allocated_vehicle_id), (self.color.pk, vehicle.pk), "沒確認就不改")

        _page, response = self._edit(order, color=str(other.pk), _confirm_unallocate="1")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["reload"])
        order.refresh_from_db()
        vehicle.refresh_from_db()
        self.assertEqual((order.color_id, order.allocated_vehicle_id, order.status),
                         (other.pk, None, SalesOrder.Status.ALLOCATION_PENDING))
        self.assertEqual(vehicle.status, AVAILABLE)
        self.assertTrue(OrderEvent.objects.filter(order=order, event_type="unallocated").exists())

    def test_confirmed_change_is_still_blocked_after_registration_started(self):
        order, vehicle = self.make_order()
        order.final_plate_number = "ABC-1234"
        order.save(update_fields=["final_plate_number", "updated_at"])
        other = VehicleColor.objects.create(vehicle_model=self.model, name="黑")
        _page, response = self._edit(order, color=str(other.pk), _confirm_unallocate="1")
        self.assertEqual(response.status_code, 400)
        self.assertIn("不能改車色：已開始領牌", response.json()["errors"]["color"][0])
        order.refresh_from_db()
        self.assertEqual((order.color_id, order.allocated_vehicle_id), (self.color.pk, vehicle.pk))

    def test_unchanged_model_and_color_saves_without_touching_allocation(self):
        order, vehicle = self.make_order()
        _page, response = self._edit(order, note="只改備註")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotIn("reload", response.json())
        order.refresh_from_db()
        self.assertEqual(order.allocated_vehicle_id, vehicle.pk)
        self.assertEqual(order.vehicle_price, Decimal("75000"))

    def test_unallocated_color_change_saves_and_reloads_allocation_candidates(self):
        """UAT 2026-11-07 T-129：未配車時改車色直接存檔，回傳重新載入，配車清單立刻換成新車色庫存。"""
        order, grey_vehicle = self.make_order()
        order.unallocate("測試人員")
        cream = VehicleColor.objects.create(vehicle_model=self.model, name="奶")
        cream_vehicle = VehicleInventory.objects.create(
            vehicle_model=self.model, color=cream, engine_number=f"CREAM-{order.pk}",
            ownership_store=self.store, location_store=self.store,
        )
        order.refresh_from_db()
        page, response = self._edit(order, color=str(cream.pk))
        self.assertNotContains(page, "data-unallocate-confirm", msg_prefix="未配車不跳換車警告")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["reload"], "改車色後要重新載入，頁首與配車清單才會更新")
        order.refresh_from_db()
        self.assertEqual((order.color_id, order.allocated_vehicle_id), (cream.pk, None))
        page = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "allocation"})
        candidates = list(page.context["allocation_form"].fields["vehicle"].queryset)
        self.assertIn(cream_vehicle, candidates)
        self.assertNotIn(grey_vehicle, candidates)
        self.assertContains(page, f"／{cream.name} 的可售庫存")
