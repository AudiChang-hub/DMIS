"""收支頁（使用者 2026-10-21 投影片 T-45～T-48）：應收設定拿掉、收款可直接刪除、刪除後的連動。"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import OrderEvent, OrderOperationsProfile, PaymentRecord, SalesOrder
from sales.services.deposit_step import confirm_intake_deposit, deposit_summary
from sales.services.operations_sync import sync_order_operations, sync_payment_financials
from sales.services.order_workspace import payment_formset_for
from sales.tests import test_payment_ledger as ledger


class FinancePageDeletionTests(TestCase):
    setUpTestData = classmethod(ledger.PaymentLedgerTests.setUpTestData.__func__)
    setUp = ledger.PaymentLedgerTests.setUp
    receipt = ledger.PaymentLedgerTests.receipt
    payload = ledger.PaymentLedgerTests.payload
    post_operations = ledger.PaymentLedgerTests.post_operations

    def delete_row(self, payment):
        payload = self.payload()
        row = next(form for form in payment_formset_for(self.order) if form.instance.pk == payment.pk)
        payload[row.add_prefix("DELETE")] = "on"
        response = self.post_operations(payload)
        self.assertEqual(response.status_code, 200, response.content)
        self.order.refresh_from_db()
        return response

    def profile(self):
        return OrderOperationsProfile.objects.get(order=self.order)

    def test_expected_amount_is_not_editable_or_shown(self):
        # T-46：應收照系統計算，送來的應收金額一律忽略，畫面也不顯示。
        balance = self.order.payment_records.get(system_key="balance")
        before = balance.expected_amount
        payload = self.payload()
        row = next(form for form in payment_formset_for(self.order) if form.instance.pk == balance.pk)
        self.assertTrue(row.fields["expected_amount"].disabled)
        payload[row.add_prefix("expected_amount")] = "99999"
        self.assertEqual(self.post_operations(payload).status_code, 200)
        balance.refresh_from_db()
        self.assertEqual((balance.expected_amount, balance.expected_amount_overridden), (before, False))
        page = self.client.get(reverse("order_detail", args=[self.order.pk]), {"tab": "finance"}).content.decode()
        self.assertNotIn("應收設定", page)
        self.assertNotIn("應收金額</label>", page)

    def test_deleting_received_deposit_returns_it_to_pending(self):
        SalesOrder.objects.filter(pk=self.order.pk).update(deposit_amount=5000, deposit_method="cash", deposit_date=date(2026, 9, 20))
        self.order.refresh_from_db()
        sync_order_operations(self.order.pk, update_receivables=True)
        deposit = confirm_intake_deposit(self.order, "測試")
        self.assertTrue(deposit.confirmed)
        self.delete_row(deposit)
        self.assertFalse(PaymentRecord.objects.filter(pk=deposit.pk).exists())
        rebuilt = self.order.payment_records.get(system_key="deposit")
        self.assertEqual((rebuilt.expected_amount, rebuilt.received_amount, rebuilt.confirmed), (Decimal("5000"), Decimal("0"), False))
        self.assertEqual(deposit_summary(self.order, rebuilt), "待收妥 5,000")
        self.assertTrue(OrderEvent.objects.filter(order=self.order, event_type="payment_deleted", description__contains="訂金").exists())

    def test_deleting_balance_reopens_the_delivery_gate(self):
        balance = self.order.payment_records.get(system_key="balance")
        balance.received_amount = balance.expected_amount
        balance.received_on = date(2026, 9, 21)
        balance.payment_method = "匯款"
        balance.confirmed = True
        balance.save()
        self.order.refresh_from_db()
        self.assertFalse(any("尾款尚未收清" in item for item in self.order.delivery_blockers()))
        self.delete_row(balance)
        self.assertTrue(any("尾款尚未收清" in item for item in self.order.delivery_blockers()))
        rebuilt = self.order.payment_records.get(system_key="balance")
        self.assertEqual((rebuilt.received_amount, rebuilt.confirmed), (Decimal("0"), False))

    def test_deleting_lender_disbursement_restores_reconciliation_and_profit(self):
        SalesOrder.objects.filter(pk=self.order.pk).update(
            payment_type="installment", installment_company="測試分期", installment_periods=24,
            installment_monthly=3000, installment_amount=70000,
            installment_plan_snapshot={"expected_disbursement_amount": "62000"})
        OrderOperationsProfile.objects.filter(order=self.order).update(actual_disbursement=62000)
        self.order.refresh_from_db()
        sync_order_operations(self.order.pk, update_receivables=True)
        before = self.profile()
        self.assertEqual(before.actual_disbursement, Decimal("62000"))
        disbursement = self.order.payment_records.get(system_key="installment_disbursement")
        disbursement.received_amount = Decimal("65000")
        disbursement.received_on = date(2026, 9, 25)
        disbursement.payment_method = "分期撥款"
        disbursement.confirmed = True
        disbursement.confirmed_at = timezone.now()
        disbursement.save()
        sync_payment_financials(self.order.pk, adopt_payment_id=disbursement.pk)
        adopted = self.profile()
        self.assertEqual(adopted.actual_disbursement, Decimal("65000"))
        self.delete_row(disbursement)
        restored = self.profile()
        self.assertEqual(restored.actual_disbursement, before.actual_disbursement)
        self.assertEqual(restored.net_profit, before.net_profit)
        self.assertEqual(restored.payment_disbursement_snapshot, {})
        rebuilt = self.order.payment_records.get(system_key="installment_disbursement")
        self.assertEqual((rebuilt.received_amount, rebuilt.confirmed), (Decimal("0"), False))
        # 統一撥款對帳：這張單回到尚未入帳。
        self.assertEqual(self.order.payment_records.filter(system_key="installment_disbursement", confirmed=True).count(), 0)
