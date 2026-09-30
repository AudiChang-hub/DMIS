from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import (
    DeliveryRecord, OrderEvent, PaymentRecord, SalesOrder, SalesSource, VehicleInventory,
    VehicleInventoryHistory,
)
from sales.services.dealer_credit import dealer_outstanding
from sales.services.order_exception import close_after_registration
from sales.services.sales_metrics import CANCELLED_STATUSES
from sales.tests import test_order_lifecycle as lifecycle


class BusinessGateTests(TestCase):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order
    delivery_payload = lifecycle.OrderLifecycleTests.delivery_payload

    def registered(self, order, plate="ABC-1234"):
        SalesOrder.objects.filter(pk=order.pk).update(
            registration_completed_at=timezone.now(), registration_date=date(2026, 8, 4),
            final_plate_number=plate, status=SalesOrder.Status.DELIVERY_PENDING,
        )
        order.refresh_from_db()
        return order

    def receive(self, order, amount, **extra):
        return PaymentRecord.objects.create(order=order, item_name="客戶付款", received_amount=Decimal(amount),
                                            received_on=date(2026, 8, 3), payment_method="匯款", confirmed=True, **extra)

    def v2(self, order):
        SalesOrder.objects.filter(pk=order.pk).update(cash_receivable_v2=True)
        PaymentRecord.objects.filter(order=order, system_key="deposit").update(received_amount=0)
        order.refresh_from_db()
        return order

    # H3：分期核貸閘門
    def test_installment_requires_approval_before_delivery(self):
        order, _vehicle = self.make_order(deposit=Decimal("0"))
        SalesOrder.objects.filter(pk=order.pk).update(payment_type="installment", installment_amount=Decimal("70000"))
        order = self.registered(order)
        self.assertTrue(any("須核准" in item for item in order.delivery_blockers()))
        with self.assertRaisesMessage(ValidationError, "須核准"):
            order.complete_delivery(timezone.now(), "測試")
        self.client.force_login(self.user)
        response = self.client.post(reverse("installment_decision_update", args=[order.pk]),
                                    {"installment_status": "approved", "installment_applied_on": "2026-08-01"})
        order.refresh_from_db()
        self.assertEqual(order.installment_status, "")
        self.client.post(reverse("installment_decision_update", args=[order.pk]), {
            "installment_status": "approved", "installment_applied_on": "2026-08-01",
            "installment_decided_on": "2026-08-02", "note": "裕融核准",
        })
        order.refresh_from_db()
        self.assertEqual(order.installment_status, SalesOrder.InstallmentStatus.APPROVED)
        self.assertFalse(any("須核准" in item for item in order.delivery_blockers()))
        self.assertTrue(OrderEvent.objects.filter(order=order, event_type="installment_decision").exists())

    def test_invoice_photo_is_optional_for_registration(self):
        from sales.models import RegistrationDocument
        order, _vehicle = self.make_order()
        self.assertNotIn(RegistrationDocument.DocumentType.INVOICE, order.required_registration_document_types())
        self.assertNotIn("發票", order.missing_registration_requirements())

    # M3：折扣待確認不可交車
    def test_pending_discount_blocks_delivery(self):
        order, _vehicle = self.make_order(dealer=True)
        SalesOrder.objects.filter(pk=order.pk).update(discount_status=SalesOrder.DiscountStatus.PENDING)
        order.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, "折扣申請尚待確認"):
            order.complete_delivery(timezone.now(), "測試")

    # M1：車行掛帳額度
    def test_dealer_credit_limit_blocks_and_on_account_is_recorded(self):
        first, _vehicle = self.make_order(dealer=True, deposit=Decimal("0"))
        first = self.v2(first)
        self.source.credit_limit = Decimal("100000")
        self.source.save()
        from sales.forms import DeliveryCompletionForm
        form = DeliveryCompletionForm(first, self.delivery_payload())
        self.assertTrue(form.is_valid(), form.errors)
        first, record = form.save("測試")
        self.assertEqual(record.on_account_amount, Decimal("75000"))
        self.assertEqual(dealer_outstanding(self.source.pk), Decimal("75000"))
        second, _vehicle = self.make_order(dealer=True, deposit=Decimal("0"))
        second = self.v2(second)
        with self.assertRaisesMessage(ValidationError, "超過額度"):
            second.complete_delivery(timezone.now(), "測試")
        self.source.credit_limit = None
        self.source.save()
        second.refresh_from_db()
        self.assertFalse(second.delivery_blockers())

    # H4：領牌後棄單例外結案
    def test_exception_close_releases_registered_vehicle_with_settlement(self):
        order, vehicle = self.make_order(deposit=Decimal("0"))
        order = self.v2(order)
        self.receive(order, "20000")
        order = self.registered(order)
        order = close_after_registration(
            order.pk, actor_name="測試", reason="貸款未過客戶放棄", forfeited_amount=Decimal("6000"),
            forfeit_reason="領牌規費與違約金", resale_price=Decimal("62000"), completed_on=date(2026, 8, 6),
            method=SalesOrder.PaymentMethod.TRANSFER, reference="末五碼 1",
        )
        vehicle.refresh_from_db()
        self.assertEqual(order.status, SalesOrder.Status.EXCEPTION_CLOSED)
        self.assertIsNone(order.allocated_vehicle_id)
        self.assertEqual(order.exception_vehicle_id, vehicle.pk)
        self.assertEqual(order.refund_amount, Decimal("14000"))
        self.assertEqual(vehicle.status, VehicleInventory.Status.AVAILABLE)
        self.assertEqual(vehicle.registered_plate_number, "ABC-1234")
        self.assertEqual(vehicle.resale_price, Decimal("62000"))
        self.assertTrue(VehicleInventoryHistory.objects.filter(vehicle=vehicle, reason__contains="已領牌車").exists())
        self.assertEqual(order.payment_records.get(entry_type="refund").received_amount, Decimal("-14000"))
        self.assertIn(SalesOrder.Status.EXCEPTION_CLOSED, CANCELLED_STATUSES)
        self.assertTrue(order.is_cancelled_sale and order.is_settled_closed)
        with self.assertRaises(ValidationError):
            close_after_registration(order.pk, actor_name="測試", reason="重複", forfeited_amount=0, forfeit_reason="",
                                     resale_price=1, completed_on=date(2026, 8, 6))

        # 已領牌車不可配給新車訂單，只能配給領牌車交易。
        new_car, _other = self.make_order(deposit=Decimal("0"))
        SalesOrder.objects.filter(pk=new_car.pk).update(allocated_vehicle=None, status=SalesOrder.Status.ALLOCATION_PENDING)
        new_car.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, "已領牌"):
            new_car.allocate(vehicle)
        SalesOrder.objects.filter(pk=new_car.pk).update(transaction_type=SalesOrder.TransactionType.REGISTERED)
        new_car.refresh_from_db()
        new_car.allocate(vehicle)
        self.assertEqual(new_car.allocated_vehicle_id, vehicle.pk)

    def test_exception_close_guards(self):
        order, _vehicle = self.make_order(deposit=Decimal("0"))
        order = self.v2(order)
        with self.assertRaisesMessage(ValidationError, "尚未完成領牌"):
            close_after_registration(order.pk, actor_name="測試", reason="x", forfeited_amount=0, forfeit_reason="",
                                     resale_price=1, completed_on=date(2026, 8, 6))
        order = self.registered(order)
        PaymentRecord.objects.create(order=order, item_name="分期撥款", receipt_kind="lender", received_amount=60000,
                                     received_on=date(2026, 8, 3), confirmed=True)
        with self.assertRaisesMessage(ValidationError, "分期公司已撥款"):
            close_after_registration(order.pk, actor_name="測試", reason="x", forfeited_amount=0, forfeit_reason="",
                                     resale_price=1, completed_on=date(2026, 8, 6))

    def test_exception_close_endpoint_and_panel(self):
        order, _vehicle = self.make_order(deposit=Decimal("0"))
        order = self.registered(self.v2(order))
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[order.pk]))
        self.assertContains(page, "領牌後棄單（例外結案）")
        response = self.client.post(reverse("order_exception_close", args=[order.pk]), {
            "reason": "客戶反悔", "forfeited_amount": "0", "resale_price": "65000", "completed_on": "2026-08-06",
        }, follow=True)
        self.assertContains(response, "已例外結案")
        order.refresh_from_db()
        self.assertEqual(order.status, SalesOrder.Status.EXCEPTION_CLOSED)
        self.assertContains(self.client.get(reverse("order_detail", args=[order.pk])), "釋回車輛")
