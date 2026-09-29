from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.forms import OrderOperationsForm
from sales.models import OrderEvent, OrderOperationsProfile, PaymentRecord, SalesOrder, payment_ledger_maintenance
from sales.services.operations_sync import sync_order_operations
from sales.services.order_next_actions import build_order_next_actions
from sales.services.order_workspace import payment_formset_for
from sales.services.payment_ledger import ledger_totals, refund_overpayment, reverse_payment, settlement_gap
from sales.services.payment_summary import payment_summary
from sales.services.sales_metrics import filter_payment_risk
from sales.tests import test_order_workspace as workspace_fixtures
from sales.tests.test_order_workspace import form_data, formset_data


class PaymentLedgerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        workspace_fixtures.OrderWorkspaceTests.setUpTestData.__func__(cls)
        SalesOrder.objects.filter(pk=cls.order.pk).update(cash_receivable_v2=True)
        sync_order_operations(cls.order.pk, update_receivables=True)

    def setUp(self):
        self.client.force_login(self.admin)
        self.order.refresh_from_db()

    def receipt(self, amount, confirmed=True, **kwargs):
        return PaymentRecord.objects.create(
            order=self.order, item_name=kwargs.pop("item_name", "客戶匯款"), received_amount=Decimal(amount),
            received_on=kwargs.pop("received_on", date(2026, 9, 21)), payment_method="匯款", confirmed=confirmed, **kwargs,
        )

    def payload(self):
        self.order.refresh_from_db()
        return {**form_data(OrderOperationsForm(instance=OrderOperationsProfile.objects.get(order=self.order), prefix="operations")),
                **formset_data(payment_formset_for(self.order))}

    def add_row(self, payload, **values):
        index = int(payload["payments-TOTAL_FORMS"])
        payload["payments-TOTAL_FORMS"] = str(index + 1)
        defaults = {"item_name": "第二筆收款", "receipt_kind": "customer", "received_amount": "20000",
                    "received_on": "2026-09-21", "payment_method": "匯款", "confirmed": "on"}
        for key, value in {**defaults, **values}.items():
            payload[f"payments-{index}-{key}"] = value
        return payload

    def post_operations(self, payload):
        return self.client.post(reverse("order_operations", args=[self.order.pk]), payload, HTTP_X_ORDER_WORKSPACE="1")

    def test_reversal_is_single_full_and_only_for_confirmed_receipts(self):
        paid = self.receipt(20000)
        reversal = reverse_payment(order_id=self.order.pk, payment_id=paid.pk, actor_name="測試", reason="重複登記")
        self.assertEqual(reversal.received_amount, Decimal("-20000"))
        self.assertEqual(reversal.reverses_id, paid.pk)
        self.assertEqual(ledger_totals(self.order)["customer"]["net"], 0)
        with self.assertRaisesMessage(ValidationError, "尚未沖銷"):
            reverse_payment(order_id=self.order.pk, payment_id=paid.pk, actor_name="測試", reason="再沖一次")
        pending = self.receipt(5000, confirmed=False)
        with self.assertRaises(ValidationError):
            reverse_payment(order_id=self.order.pk, payment_id=pending.pk, actor_name="測試", reason="未確認")
        with self.assertRaises(ValidationError):
            reverse_payment(order_id=self.order.pk, payment_id=reversal.pk, actor_name="測試", reason="沖銷列")
        with self.assertRaisesMessage(ValidationError, "請填寫原因"):
            reverse_payment(order_id=self.order.pk, payment_id=self.receipt(1000).pk, actor_name="測試", reason=" ")
        self.assertTrue(OrderEvent.objects.filter(order=self.order, event_type="payment_reversed").exists())

    def test_adjustments_are_immutable_and_constrained(self):
        reversal = reverse_payment(order_id=self.order.pk, payment_id=self.receipt(20000).pk, actor_name="測試", reason="錯帳")
        reversal.adjustment_reason = "改寫原因"
        with self.assertRaisesMessage(ValidationError, "不可修改"):
            reversal.save()
        reversal.refresh_from_db()
        with self.assertRaises(ValidationError):
            reversal.delete()
        with self.assertRaises(IntegrityError), transaction.atomic():
            PaymentRecord.objects.filter(pk=reversal.pk).update(received_amount=5)
        with self.assertRaisesMessage(ValidationError, "不可為負數"):
            self.receipt(-100)
        with self.assertRaises(ValidationError):
            PaymentRecord.objects.create(order=self.order, item_name="無原因退款", entry_type="refund",
                                         received_amount=-100, confirmed=True)

    def test_unconfirmed_manual_receipt_can_still_be_deleted(self):
        pending = self.receipt(3000, confirmed=False)
        pending.delete()
        self.assertFalse(PaymentRecord.objects.filter(pk=pending.pk).exists())

    def test_overpayment_is_visible_and_refund_is_capped(self):
        self.receipt(75000)
        summary = payment_summary(self.order)
        self.assertEqual(summary["customer_overpaid"], 5000)
        self.assertTrue(filter_payment_risk(SalesOrder.objects.filter(pk=self.order.pk), "overpaid").exists())
        with self.assertRaisesMessage(ValidationError, "不超過溢收 5,000"):
            refund_overpayment(order_id=self.order.pk, kind="customer", amount=6000, actor_name="測試",
                               reason="多匯", method_label="匯款", refunded_on=date(2026, 9, 22))
        refund = refund_overpayment(order_id=self.order.pk, kind="customer", amount=5000, actor_name="測試",
                                    reason="客戶多匯", method_label="匯款", refunded_on=date(2026, 9, 22))
        self.assertEqual(refund.received_amount, Decimal("-5000"))
        self.assertEqual(payment_summary(self.order)["customer_overpaid"], 0)
        self.assertFalse(filter_payment_risk(SalesOrder.objects.filter(pk=self.order.pk), "overpaid").exists())

    def test_overpayment_refund_endpoint(self):
        self.receipt(72000)
        response = self.client.post(reverse("payment_overpayment_refund", args=[self.order.pk]), {
            "kind": "customer", "amount": "2000", "refunded_on": "2026-09-22", "method": "transfer",
            "reference": "末五碼 11111", "reason": "客戶多匯", "return_to": "operations",
        })
        self.assertRedirects(response, reverse("order_operations", args=[self.order.pk]))
        self.assertEqual(ledger_totals(self.order)["customer"]["refunded"], 2000)

    def test_reverse_endpoint_and_ledger_panel(self):
        paid = self.receipt(20000)
        page = self.client.get(reverse("order_operations", args=[self.order.pk]))
        self.assertContains(page, "沖銷登記錯誤的收款")
        self.assertContains(page, "data-payment-locked")
        response = self.client.post(reverse("payment_reverse", args=[self.order.pk]),
                                    {"payment": paid.pk, "reason": "金額錯誤", "return_to": "operations"})
        self.assertRedirects(response, reverse("order_operations", args=[self.order.pk]))
        self.assertTrue(paid.reversal_entries.exists())
        page = self.client.get(reverse("order_operations", args=[self.order.pk]))
        self.assertContains(page, "金額錯誤")

    def test_duplicate_receipt_requires_acknowledgement(self):
        self.receipt(20000)
        response = self.post_operations(self.add_row(self.payload()))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.order.payment_records.filter(received_amount=20000).count(), 1)
        response = self.post_operations(self.add_row(self.payload(), duplicate_confirmed="on"))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.order.payment_records.filter(received_amount=20000, confirmed=True).count(), 2)
        self.assertTrue(OrderEvent.objects.filter(order=self.order, event_type="duplicate_payment_confirmed").exists())

    def test_confirmed_receipt_cannot_be_deleted_from_operations(self):
        paid = self.receipt(20000)
        payload = self.payload()
        row = next(form for form in payment_formset_for(self.order) if form.instance.pk == paid.pk)
        payload[row.add_prefix("DELETE")] = "on"
        response = self.post_operations(payload)
        self.assertEqual(response.status_code, 400)
        self.assertTrue(PaymentRecord.objects.filter(pk=paid.pk).exists())

    def test_cancelled_order_payments_are_read_only(self):
        SalesOrder.objects.filter(pk=self.order.pk).update(status=SalesOrder.Status.CANCELLED)
        before = list(self.order.payment_records.values_list("pk", "received_amount", "confirmed"))
        # 唯讀列的輸入一律忽略，不會新增或改寫任何收款。
        self.post_operations(self.add_row(self.payload(), received_amount="999", received_on="2026-09-25"))
        self.assertEqual(list(self.order.payment_records.values_list("pk", "received_amount", "confirmed")), before)
        page = self.client.get(reverse("order_operations", args=[self.order.pk]))
        self.assertContains(page, "訂單已取消，收款已結算")
        self.assertNotContains(page, 'id="add-payment"')

    def test_cancel_pending_does_not_rewrite_agreed_deposit(self):
        SalesOrder.objects.filter(pk=self.order.pk).update(deposit_amount=5000, status=SalesOrder.Status.CANCEL_REFUND_PENDING)
        sync_order_operations(self.order.pk, update_receivables=True)
        payload = self.payload()
        deposit = self.order.payment_records.get(system_key="deposit")
        row = next(form for form in payment_formset_for(self.order) if form.instance.pk == deposit.pk)
        payload[row.add_prefix("expected_amount")] = "1000"
        payload[row.add_prefix("expected_amount_override_reason")] = "測試"
        self.post_operations(payload)
        self.order.refresh_from_db()
        self.assertEqual(self.order.deposit_amount, 5000)

    def test_cancel_pending_order_content_is_locked(self):
        SalesOrder.objects.filter(pk=self.order.pk).update(status=SalesOrder.Status.CANCEL_REFUND_PENDING)
        self.order.refresh_from_db()
        self.assertFalse(self.order.can_edit_content)
        self.assertFalse(self.order.is_editable)

    def test_settlement_gap_after_delivery_correction(self):
        self.receipt(70000)
        SalesOrder.objects.filter(pk=self.order.pk).update(status=SalesOrder.Status.COMPLETED, delivered_at=timezone.now())
        self.order.refresh_from_db()
        self.assertIsNone(settlement_gap(self.order))
        payload = self.payload()
        balance = self.order.payment_records.get(system_key="balance")
        row = next(form for form in payment_formset_for(self.order) if form.instance.pk == balance.pk)
        payload[row.add_prefix("expected_amount")] = "72000"
        payload[row.add_prefix("expected_amount_override_reason")] = "交付後補收牌照費"
        response = self.post_operations(payload)
        self.assertEqual(response.status_code, 200, response.content)
        self.order.refresh_from_db()
        self.assertEqual(settlement_gap(self.order), {"due": 2000, "overpaid": 0})
        event = OrderEvent.objects.filter(order=self.order, event_type="settlement_gap").get()
        self.assertIn("待補收 2,000", event.description)
        actions = build_order_next_actions(self.order)
        self.assertEqual(actions.primary.key, "settlement-gap")

    def test_controlled_import_may_rewrite_confirmed_receipt(self):
        paid = self.receipt(20000)
        paid.received_amount = 21000
        with payment_ledger_maintenance():
            paid.save()
        paid.refresh_from_db()
        self.assertEqual(paid.received_amount, 21000)

    def test_migration_marks_only_existing_cancelled_orders(self):
        import importlib
        from django.apps import apps
        SalesOrder.objects.filter(pk=self.order.pk).update(status=SalesOrder.Status.CANCELLED)
        module = importlib.import_module("sales.migrations.0152_payment_ledger")
        module.mark_legacy_refunds(apps, None)
        self.order.refresh_from_db()
        self.assertTrue(self.order.refund_settled_legacy)
        self.assertEqual(SalesOrder.objects.filter(refund_settled_legacy=True).count(), 1)
