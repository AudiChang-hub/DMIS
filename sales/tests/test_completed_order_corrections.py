from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django import forms
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.forms import AccessoryFormSet, OrderEditForm
from sales.models import (
    DealerVolumeBonusRule, DealerVolumeBonusTier, OrderChange, OrderEvent,
    SalesOrder, SalesSource, ScreenAccessGrant, Store, UserAccessState,
    VehicleColor, VehicleInventory, VehicleModel,
)
from sales.services.dealer_commission import create_volume_bonus_settlement


class CompletedOrderCorrectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("correction-editor", password="test-only-123")
        cls.dealer = SalesSource.objects.create(name="修正測試車行", source_type="dealer")
        cls.model = VehicleModel.objects.create(brand="SYM", name="修正測試機種", energy_type="gas")
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="白")

    def setUp(self):
        self.client.force_login(self.user)

    def order(self, **overrides):
        data = dict(source_type="dealer", source=self.dealer,
                    owner_type="local", owner_name="測試車主", owner_id_number="A123456789",
                    owner_phone="0912345678", owner_address="測試地址",
                    vehicle_model=self.model, color=self.color, vehicle_price=70000,
                    actual_balance=71234, plate_insurance_fee=1234,
                    registration_plate_fee=1234, registration_calculated_total=1234,
                    payment_type="cash", delivery_method="store_pickup", status=SalesOrder.Status.COMPLETED,
                    order_date=date(2026, 9, 1), registration_date=date(2026, 9, 2))
        data.update(overrides)
        return SalesOrder.objects.create(**data)

    def payload(self, order, **overrides):
        data = {}
        for bound in OrderEditForm(instance=order):
            if isinstance(bound.field, forms.FileField):
                continue
            value = bound.value()
            if isinstance(bound.field, forms.BooleanField):
                if value:
                    data[bound.name] = "on"
            else:
                data[bound.name] = "" if value is None else str(value)
        for prefix in (AccessoryFormSet.get_default_prefix(), "other_fees"):
            data.update({f"{prefix}-TOTAL_FORMS": "0", f"{prefix}-INITIAL_FORMS": "0",
                         f"{prefix}-MIN_NUM_FORMS": "0", f"{prefix}-MAX_NUM_FORMS": "1000"})
        data.update(_order_revision=order.revision, change_reason="修正聯絡資料",
                    confirm_completed_correction="on", note="修正後備註")
        data.update(overrides)
        return data

    def post(self, order, **overrides):
        return self.client.post(reverse("order_edit", args=[order.pk]), self.payload(order, **overrides))

    def assert_saved(self, response, order):
        if response.status_code == 200:
            self.fail(str(response.context["form"].errors) + str(response.context["formset"].errors)
                      + str(response.context["fee_formset"].errors))
        self.assertRedirects(response, reverse("order_detail", args=[order.pk]), fetch_redirect_response=False)
        order.refresh_from_db()

    def test_completed_and_delivered_orders_can_be_repeatedly_corrected_with_audit(self):
        for status in (SalesOrder.Status.COMPLETED, SalesOrder.Status.DELIVERED_DOCS_PENDING):
            with self.subTest(status=status):
                order = self.order(status=status)
                delivered_at = order.delivered_at
                self.assertContains(self.client.get(reverse("order_edit", args=[order.pk])), "完成後修正")
                self.assertContains(self.client.get(reverse("order_detail", args=[order.pk])), "編輯訂單（完成後修正）")
                for number in (1, 2):
                    self.assert_saved(self.post(order, note=f"修正 {number}"), order)
                    self.assertEqual(order.note, f"修正 {number}")
                    self.assertEqual(order.status, status)
                    self.assertEqual(order.delivered_at, delivered_at)
                    self.assertEqual(order.revision, number + 1)
                    self.assertFalse(order.id_verified)
                self.assertEqual(OrderChange.objects.filter(order=order).count(), 2)
                event = OrderEvent.objects.filter(order=order, event_type="updated").first()
                self.assertIn("完成後修正", event.description)
                self.assertTrue(event.actor_name)

    def test_confirmation_and_reason_are_required_server_side(self):
        order = self.order()
        for field in ("confirm_completed_correction", "change_reason"):
            response = self.post(order, **{field: ""})
            self.assertEqual(response.status_code, 200)
            self.assertIn(field, response.context["form"].errors)
        order.refresh_from_db()
        self.assertEqual(order.revision, 1)
        self.assertFalse(OrderChange.objects.filter(order=order).exists())
        pending = self.order(status=SalesOrder.Status.ALLOCATION_PENDING)
        self.assertNotIn("confirm_completed_correction", OrderEditForm(instance=pending).fields)

    def test_note_correction_keeps_historical_fees_snapshots_and_receipts(self):
        order = self.order(price_snapshot={"historical": "price"}, installment_plan_snapshot={"historical": "installment"})
        payment = order.payment_records.get(system_key="balance")
        payment.received_amount, payment.confirmed = 71234, True
        payment.save()
        with patch("sales.views.apply_order_price_snapshot") as price, \
             patch("sales.views.apply_order_installment_snapshot") as installment, \
             patch("sales.services.financial_refresh.refresh_unlocked_financials") as refresh:
            self.assert_saved(self.post(order, owner_phone="0987654321", registration_plate_fee="9999"), order)
            price.assert_not_called()
            installment.assert_not_called()
            refresh.assert_not_called()
        payment.refresh_from_db()
        self.assertEqual(order.registration_plate_fee, 1234)
        self.assertEqual(order.plate_insurance_fee, 1234)
        self.assertEqual(order.price_snapshot, {"historical": "price"})
        self.assertEqual(payment.received_amount, 71234)
        self.assertTrue(payment.confirmed)

    def test_missing_historical_snapshots_are_not_backfilled(self):
        order = self.order()
        SalesOrder.objects.filter(pk=order.pk).update(delivered_at=None, delivered_by="")
        order.refresh_from_db()
        with patch("sales.views.apply_order_price_snapshot") as price, \
             patch("sales.views.apply_order_installment_snapshot") as installment:
            self.assert_saved(self.post(order), order)
            price.assert_not_called()
            installment.assert_not_called()
        self.assertEqual(order.price_snapshot, {})
        self.assertEqual(order.installment_plan_snapshot, {})
        self.assertIsNone(order.delivered_at)
        self.assertEqual(order.delivered_by, "")

    def test_explicit_price_correction_updates_receivable_not_receipt(self):
        order = self.order()
        payment = order.payment_records.get(system_key="balance")
        payment.received_amount, payment.confirmed = 71234, True
        payment.save()
        self.assert_saved(self.post(order, vehicle_price="80000", vehicle_price_adjustment_reason="修正成交價"), order)
        payment.refresh_from_db()
        self.assertEqual(order.actual_balance, Decimal("81234"))
        self.assertEqual(payment.expected_amount, 81234)
        self.assertEqual(payment.received_amount, 71234)
        self.assertEqual(payment.outstanding_amount, 10000)
        self.assertEqual(order.status, SalesOrder.Status.COMPLETED)

    def test_changed_identity_still_requires_documents(self):
        order = self.order()
        response = self.post(order, owner_name="另一位車主")
        self.assertEqual(response.status_code, 200)
        self.assertIn("id_front", response.context["form"].errors)
        self.assertIn("id_verified", response.context["form"].errors)

    def test_cancelled_and_stale_order_cannot_be_changed(self):
        cancelled = self.order(status=SalesOrder.Status.CANCELLED)
        self.assertEqual(self.post(cancelled).status_code, 302)
        cancelled.refresh_from_db()
        self.assertEqual(cancelled.note, "")
        order = self.order(revision=2)
        self.assertRedirects(self.post(order, _order_revision=1), reverse("order_edit", args=[order.pk]), fetch_redirect_response=False)
        order.refresh_from_db()
        self.assertEqual(order.note, "")

    def test_view_only_permission_cannot_edit_completed_order(self):
        order = self.order()
        UserAccessState.objects.create(user=self.user, configured=True)
        ScreenAccessGrant.objects.create(user=self.user, screen_key="orders", view=True)
        url = reverse("order_edit", args=[order.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.post(order).status_code, 403)
        self.assertNotContains(self.client.get(reverse("order_detail", args=[order.pk])), "編輯訂單（完成後修正）")

    def test_allocated_vehicle_color_cannot_be_rewritten(self):
        store = Store.objects.create(name="修正測試店", code="FIX")
        vehicle = VehicleInventory.objects.create(vehicle_model=self.model, color=self.color,
                    engine_number="CORRECTION-001", ownership_store=store, location_store=store)
        order = self.order(allocated_vehicle=vehicle)
        other_color = VehicleColor.objects.create(vehicle_model=self.model, name="黑")
        response = self.post(order, color=str(other_color.pk))
        self.assertEqual(response.status_code, 200)
        self.assertIn("color", response.context["form"].errors)
        order.refresh_from_db()
        self.assertEqual(order.color, self.color)

    def test_settled_order_allows_notes_but_protects_registration_period(self):
        rule = DealerVolumeBonusRule.objects.create(dealer=self.dealer, brand="SYM",
                    starts_on=date(2026, 9, 1), ends_on=date(2026, 9, 30))
        DealerVolumeBonusTier.objects.create(rule=rule, minimum_quantity=1, bonus_per_vehicle=500)
        order = self.order(registration_completed_at=timezone.now())
        create_volume_bonus_settlement(rule, "test")
        self.assert_saved(self.post(order), order)
        other = SalesSource.objects.create(name="另一測試車行", source_type="dealer")
        response = self.post(order, source=str(other.pk))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        order.refresh_from_db()
        self.assertEqual(order.registration_date, date(2026, 9, 2))
        self.assertEqual(order.source_id, self.dealer.pk)
