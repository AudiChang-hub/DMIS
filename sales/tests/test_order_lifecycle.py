from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.forms import DeliveryCompletionForm
from sales.models import (
    BusinessHoliday,
    DeliveryRecord,
    OrderOperationsProfile,
    SalesOrder,
    SalesSource,
    Store,
    VehicleColor,
    VehicleInventory,
    VehicleModel,
)
from sales.services.business_days import add_business_days, build_dealer_reminders


class BusinessDayTests(TestCase):
    def test_weekend_and_holiday_are_excluded(self):
        BusinessHoliday.objects.create(
            date=date(2026, 8, 10), name="測試國定假日"
        )

        self.assertEqual(
            add_business_days(date(2026, 8, 7), 3),
            date(2026, 8, 13),
        )


class OrderLifecycleTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="lifecycle", password="test-pass-123"
        )
        self.store = Store.objects.create(name="總店", code="HQ")
        self.source = SalesSource.objects.create(
            name="合作車行甲",
            source_type=SalesOrder.SourceType.DEALER,
        )
        self.model = VehicleModel.objects.create(
            brand="SUZUKI",
            name="SUI 125",
            model_number="UQ125DA",
            model_year=2026,
            model_code="front_disc_rear_drum",
            displacement_cc=125,
            energy_type=VehicleModel.EnergyType.GAS,
        )
        self.color = VehicleColor.objects.create(
            vehicle_model=self.model, name="灰"
        )

    def make_order(self, dealer=False, deposit=Decimal("5000")):
        order = SalesOrder.objects.create(
            owner_name="王小明",
            owner_phone="0912345678",
            owner_address="新北市汐止區",
            owner_id_number="A123456789",
            vehicle_model=self.model,
            color=self.color,
            source_type=(
                SalesOrder.SourceType.DEALER
                if dealer
                else SalesOrder.SourceType.STORE
            ),
            source=self.source if dealer else None,
            vehicle_price=Decimal("75000"),
            deposit_amount=deposit,
            actual_balance=Decimal("70000"),
            status=SalesOrder.Status.ALLOCATION_PENDING,
        )
        order.calculated_balance = order.calculate_balance()
        order.actual_balance = order.calculated_balance
        order.save(
            update_fields=["calculated_balance", "actual_balance", "updated_at"]
        )
        vehicle = VehicleInventory.objects.create(
            vehicle_model=self.model,
            color=self.color,
            engine_number=f"ENG-{order.pk}",
            ownership_store=self.store,
            location_store=self.store,
        )
        order.allocate(vehicle)
        return order, vehicle

    def delivery_payload(self, method=SalesOrder.DeliveryMethod.STORE_PICKUP):
        return {
            "delivery_method": method,
            "delivery_destination": "新北市汐止區康寧街470號",
            "delivered_at": "2026-08-05T15:30",
            "recipient_name": "王小明",
            "recipient_phone": "0912345678",
            "carrier_name": "",
            "handover_location": "新北市汐止區康寧街470號",
            "vehicle_condition_note": DeliveryCompletionForm.VEHICLE_CONDITION_NORMAL,
            "condition_checked": "on",
            "documents_checked": "on",
            "keys_checked": "on",
            "accessories_checked": "on",
            "payment_checked": "on",
            "damage_note": "",
            "note": "",
        }

    def test_dealer_can_deliver_before_registration(self):
        order, vehicle = self.make_order(dealer=True)
        form = DeliveryCompletionForm(order, self.delivery_payload())
        self.assertTrue(form.is_valid(), form.errors)

        delivered, record = form.save("測試人員")

        delivered.refresh_from_db()
        vehicle.refresh_from_db()
        self.assertEqual(
            delivered.status, SalesOrder.Status.DELIVERED_DOCS_PENDING
        )
        self.assertEqual(vehicle.status, VehicleInventory.Status.DELIVERED)
        self.assertEqual(record.recipient_name, "王小明")
        self.assertEqual(
            record.vehicle_condition_note,
            DeliveryCompletionForm.VEHICLE_CONDITION_NORMAL,
        )
        self.assertFalse(record.damage_found)

    def test_store_order_cannot_deliver_before_registration(self):
        order, _vehicle = self.make_order()
        form = DeliveryCompletionForm(order, self.delivery_payload())
        self.assertTrue(form.is_valid(), form.errors)

        with self.assertRaisesMessage(ValidationError, "必須先完成領牌"):
            form.save("測試人員")

        self.assertFalse(DeliveryRecord.objects.filter(order=order).exists())

    def test_carrier_requires_carrier_name(self):
        order, _vehicle = self.make_order(dealer=True)
        form = DeliveryCompletionForm(
            order,
            self.delivery_payload(SalesOrder.DeliveryMethod.CARRIER),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("carrier_name", form.errors)

    def test_damage_condition_requires_note_and_sets_damage_flag(self):
        order, _vehicle = self.make_order(dealer=True)
        payload = self.delivery_payload()
        payload["vehicle_condition_note"] = (
            DeliveryCompletionForm.VEHICLE_CONDITION_DAMAGED
        )

        form = DeliveryCompletionForm(order, payload)
        self.assertFalse(form.is_valid())
        self.assertIn("damage_note", form.errors)

        payload["damage_note"] = "右側車殼有刮痕"
        form = DeliveryCompletionForm(order, payload)
        self.assertTrue(form.is_valid(), form.errors)

        _delivered, record = form.save("測試人員")
        self.assertTrue(record.damage_found)
        self.assertEqual(record.damage_note, "右側車殼有刮痕")

    def test_other_condition_requires_delivery_note(self):
        order, _vehicle = self.make_order(dealer=True)
        payload = self.delivery_payload()
        payload["vehicle_condition_note"] = (
            DeliveryCompletionForm.VEHICLE_CONDITION_OTHER
        )

        form = DeliveryCompletionForm(order, payload)
        self.assertFalse(form.is_valid())
        self.assertIn("note", form.errors)

        payload["note"] = "客戶要求返店後再確認異音"
        form = DeliveryCompletionForm(order, payload)
        self.assertTrue(form.is_valid(), form.errors)

        _delivered, record = form.save("測試人員")
        self.assertEqual(record.note, "客戶要求返店後再確認異音")
        self.assertFalse(record.damage_found)

    def test_legacy_free_text_condition_post_remains_compatible(self):
        order, _vehicle = self.make_order(dealer=True)
        payload = self.delivery_payload()
        payload.update(
            {
                "vehicle_condition_note": "外觀有舊刮痕，功能正常",
                "damage_found": "on",
                "damage_note": "交付前既有痕跡",
            }
        )

        form = DeliveryCompletionForm(order, payload)
        self.assertTrue(form.is_valid(), form.errors)

        _delivered, record = form.save("測試人員")
        self.assertEqual(record.vehicle_condition_note, "外觀有舊刮痕，功能正常")
        self.assertTrue(record.damage_found)

    def test_cancellation_releases_vehicle_and_waits_for_full_refund(self):
        order, vehicle = self.make_order()

        order.request_cancellation("測試人員", "客戶改變心意", "電話確認")

        order.refresh_from_db()
        vehicle.refresh_from_db()
        self.assertEqual(order.status, SalesOrder.Status.CANCEL_REFUND_PENDING)
        self.assertIsNone(order.allocated_vehicle_id)
        self.assertEqual(vehicle.status, VehicleInventory.Status.AVAILABLE)
        with self.assertRaisesMessage(ValidationError, "必須全數退還"):
            order.complete_refund(
                "測試人員",
                Decimal("3000"),
                date(2026, 8, 5),
                SalesOrder.PaymentMethod.TRANSFER,
            )

        order.complete_refund(
            "測試人員",
            Decimal("5000"),
            date(2026, 8, 5),
            SalesOrder.PaymentMethod.TRANSFER,
            "末五碼 12345",
        )
        order.refresh_from_db()
        self.assertEqual(order.status, SalesOrder.Status.CANCELLED)
        self.assertEqual(order.refund_amount, Decimal("5000"))

    def test_registered_order_cannot_be_cancelled(self):
        order, _vehicle = self.make_order()
        order.registration_completed_at = timezone.now()
        order.save(update_fields=["registration_completed_at", "updated_at"])

        with self.assertRaisesMessage(ValidationError, "已領牌"):
            order.request_cancellation("測試人員", "客戶改變心意")

    def test_dealer_reminders_use_three_and_seven_business_days(self):
        order, _vehicle = self.make_order(dealer=True)
        delivered_at = timezone.make_aware(datetime(2026, 8, 3, 10, 0))
        order.delivered_at = delivered_at
        order.delivered_by = "測試人員"
        order.status = SalesOrder.Status.DELIVERED_DOCS_PENDING
        order.save(
            update_fields=["delivered_at", "delivered_by", "status", "updated_at"]
        )
        profile = OrderOperationsProfile.objects.get(order=order)
        profile.payment_confirmed = False
        profile.save(update_fields=["payment_confirmed", "updated_at"])

        reminders = build_dealer_reminders(date(2026, 8, 12))
        by_kind = {item["kind"]: item for item in reminders}

        self.assertEqual(
            by_kind["registration_documents"]["due_date"], date(2026, 8, 6)
        )
        self.assertEqual(by_kind["dealer_balance"]["due_date"], date(2026, 8, 12))
        self.assertTrue(by_kind["registration_documents"]["is_overdue"])
        self.assertTrue(by_kind["dealer_balance"]["is_due"])

    def test_delivery_and_refund_endpoints_explain_failures(self):
        order, _vehicle = self.make_order()
        self.client.force_login(self.user)

        delivery = self.client.post(
            reverse("delivery_complete", args=[order.pk]),
            self.delivery_payload(),
            follow=True,
        )
        self.assertContains(delivery, "一般訂單必須先完成領牌")

        cancel = self.client.post(
            reverse("cancellation_request", args=[order.pk]),
            {"reason": "客戶取消", "note": ""},
            follow=True,
        )
        self.assertContains(cancel, "必須全額退還訂金")
        self.assertContains(cancel, "確認退款並完成取消")

    def test_delivery_endpoint_does_not_lock_nullable_outer_join(self):
        order, vehicle = self.make_order(dealer=True)
        self.client.force_login(self.user)

        # 這個請求在 PostgreSQL 會直接驗證 select_for_update 沒有套到
        # nullable outer join；SQLite 仍驗證完整交付流程不受修改影響。
        response = self.client.post(
            reverse("delivery_complete", args=[order.pk]),
            self.delivery_payload(),
        )

        self.assertRedirects(
            response,
            f"{reverse('order_detail', args=[order.pk])}?tab=delivery",
        )
        order.refresh_from_db()
        vehicle.refresh_from_db()
        self.assertEqual(order.status, SalesOrder.Status.DELIVERED_DOCS_PENDING)
        self.assertEqual(vehicle.status, VehicleInventory.Status.DELIVERED)

    def test_delivery_endpoint_rejects_damage_without_note_without_side_effects(self):
        order, vehicle = self.make_order(dealer=True)
        self.client.force_login(self.user)
        payload = self.delivery_payload()
        payload["vehicle_condition_note"] = (
            DeliveryCompletionForm.VEHICLE_CONDITION_DAMAGED
        )

        response = self.client.post(
            reverse("delivery_complete", args=[order.pk]), payload, follow=True
        )

        self.assertContains(response, "發現刮傷或損壞時必須填寫說明")
        self.assertFalse(DeliveryRecord.objects.filter(order=order).exists())
        order.refresh_from_db()
        vehicle.refresh_from_db()
        self.assertEqual(order.status, SalesOrder.Status.ALLOCATED)
        self.assertEqual(vehicle.status, VehicleInventory.Status.RESERVED)

    def test_delivery_endpoint_ignores_duplicate_submission(self):
        order, _vehicle = self.make_order(dealer=True)
        self.client.force_login(self.user)
        endpoint = reverse("delivery_complete", args=[order.pk])

        self.client.post(endpoint, self.delivery_payload())
        response = self.client.post(endpoint, self.delivery_payload(), follow=True)

        self.assertContains(response, "此訂單已完成交付，不需要重複送出")
        self.assertEqual(DeliveryRecord.objects.filter(order=order).count(), 1)

    def test_delivery_tab_renders_accessible_condition_choices_and_action_bar(self):
        order, _vehicle = self.make_order(dealer=True)
        self.client.force_login(self.user)

        response = self.client.get(
            f"{reverse('order_detail', args=[order.pk])}?tab=delivery"
        )

        self.assertContains(response, '<fieldset class="wide delivery-condition-field">')
        self.assertContains(response, 'name="vehicle_condition_note"', count=3)
        self.assertContains(response, 'class="delivery-completion-actions"')
        self.assertContains(response, "確認完成交付", count=2)

    def test_completed_delivery_renders_structured_summary_and_note(self):
        order, _vehicle = self.make_order(dealer=True)
        self.client.force_login(self.user)
        payload = self.delivery_payload(SalesOrder.DeliveryMethod.CARRIER)
        payload.update(
            {
                "carrier_name": "安心託運",
                "vehicle_condition_note": DeliveryCompletionForm.VEHICLE_CONDITION_DAMAGED,
                "damage_note": "右側車殼有刮痕",
                "note": "送達前請先聯絡收車人",
            }
        )

        self.client.post(reverse("delivery_complete", args=[order.pk]), payload)
        response = self.client.get(
            f"{reverse('order_detail', args=[order.pk])}?tab=delivery"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="delivery-complete__grid"')
        self.assertContains(response, "安心託運")
        self.assertContains(response, "右側車殼有刮痕")
        self.assertContains(response, "送達前請先聯絡收車人")
        self.assertContains(response, "交付備註")
        self.assertNotContains(response, 'class="data-list delivery-summary"')

    def test_completed_delivery_does_not_present_other_condition_as_normal(self):
        order, _vehicle = self.make_order(dealer=True)
        self.client.force_login(self.user)
        payload = self.delivery_payload()
        payload.update(
            {
                "vehicle_condition_note": DeliveryCompletionForm.VEHICLE_CONDITION_OTHER,
                "note": "車主要求交車後自行調整後照鏡",
            }
        )

        self.client.post(reverse("delivery_complete", args=[order.pk]), payload)
        response = self.client.get(
            f"{reverse('order_detail', args=[order.pk])}?tab=delivery"
        )

        self.assertContains(response, "其他狀況")
        self.assertContains(response, "詳見下方交付備註")
        self.assertContains(response, "車主要求交車後自行調整後照鏡")
        self.assertNotContains(response, "交付核對已完成")

    def test_delivered_legacy_order_without_record_has_safe_summary(self):
        order, _vehicle = self.make_order(dealer=True)
        SalesOrder.objects.filter(pk=order.pk).update(
            status=SalesOrder.Status.DELIVERED_DOCS_PENDING,
            delivered_at=timezone.make_aware(datetime(2026, 8, 5, 15, 30)),
        )
        self.client.force_login(self.user)

        response = self.client.get(
            f"{reverse('order_detail', args=[order.pk])}?tab=delivery"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "詳細交付資料未建立")
        self.assertContains(response, "既有完成狀態不受影響")

    def test_delivered_legacy_order_without_timestamp_has_clear_fallback(self):
        order, _vehicle = self.make_order(dealer=True)
        SalesOrder.objects.filter(pk=order.pk).update(
            status=SalesOrder.Status.DELIVERED_DOCS_PENDING,
            delivered_at=None,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            f"{reverse('order_detail', args=[order.pk])}?tab=delivery"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "已完成交付（時間未記錄）")
