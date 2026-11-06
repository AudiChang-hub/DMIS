"""已取消訂單不留系統未收應收列（使用者 2026-11-06 選 B）。

取消完成時清除系統產生、未確認、實收 0 的應收列；已確認實收、退款紀錄、已入帳撥款與人工列不動；
已取消的單之後同步不再重建；既有資料用 clear_cancelled_receivables 指令回填（dry-run／--apply／--rollback）。
"""
from datetime import date
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.urls import reverse

from sales.models import OrderChange, PaymentRecord, SalesOrder
from sales.services.cancelled_receivables import CLEAR_REASON, clear_cancelled_receivables
from sales.services.operations_sync import sync_order_operations
from sales.tests.test_finance_ledger import FinanceLedgerTestBase
from sales.tests import test_payout_reconciliation_t96 as t96

CANCELLED = SalesOrder.Status.CANCELLED


class CancelledReceivablesTests(FinanceLedgerTestBase):
    platform_order = t96.PayoutReconciliationTests.platform_order
    installment_order = t96.PayoutReconciliationTests.installment_order

    def keys(self, order):
        return sorted(order.payment_records.values_list("system_key", flat=True))

    def confirm_deposit(self, order, amount="2000"):
        row = order.payment_records.get(system_key="deposit")
        row.expected_amount = row.received_amount = Decimal(amount)
        row.received_on = date(2026, 9, 2)
        row.payment_method = "匯款"
        row.confirmed = True
        row.save()
        return row

    def test_cash_order_cancel_clears_system_receivables_and_sync_does_not_rebuild(self):
        order = self.make_order(source_type="store", source=self.staff, deposit_amount=Decimal("2000"),
                                cash_receivable_v2=True)
        self.assertEqual(self.keys(order), ["balance", "deposit"])
        order.request_cancellation("測試人員", "重複開單")
        order.refresh_from_db()
        self.assertEqual(order.status, CANCELLED)
        self.assertEqual(self.keys(order), [])
        change = OrderChange.objects.get(order=order, reason=CLEAR_REASON)
        self.assertEqual(len(change.changes), 2)
        self.assertTrue(all(entry["after"] == "已清除" and entry["row"]["order_id"] == order.pk
                            for entry in change.changes.values()))
        self.assertTrue(order.events.filter(event_type="cancelled_receivables_cleared").exists())
        sync_order_operations(order.pk, update_receivables=True)
        self.assertEqual(self.keys(order), [], "已取消的單同步後不重建應收列")
        self.assertEqual(order.get_status_display(), "已取消")

    def test_installment_and_platform_cancel_clear_payout_rows_and_leave_reconciliation(self):
        self.client.force_login(self.admin)
        installment = self.installment_order()
        platform = self.platform_order()
        self.assertIn("installment_disbursement", self.keys(installment))
        self.assertIn("platform_disbursement", self.keys(platform))
        for order in (installment, platform):
            order.request_cancellation("測試人員", "")
            order.refresh_from_db()
            self.assertEqual((order.status, self.keys(order)), (CANCELLED, []))
        response = self.client.get(reverse("reconciliation_list"), {"status": "pending"})
        listed = {record.order_id for record in response.context["records"]}
        self.assertFalse(listed & {installment.pk, platform.pk})

    def test_confirmed_receipt_waits_for_refund_settlement_and_keeps_ledger(self):
        order = self.make_order(source_type="store", source=self.staff, deposit_amount=Decimal("2000"),
                                cash_receivable_v2=True)
        deposit = self.confirm_deposit(order)
        order.request_cancellation("測試人員", "")
        order.refresh_from_db()
        self.assertEqual(order.status, SalesOrder.Status.CANCEL_REFUND_PENDING)
        self.assertIn("balance", self.keys(order), "待退款結算前不清除")
        order.complete_refund("測試人員", Decimal("0"), date(2026, 9, 5), SalesOrder.PaymentMethod.TRANSFER)
        order.refresh_from_db()
        self.assertEqual(order.status, CANCELLED)
        rows = list(order.payment_records.order_by("pk").values_list("pk", "entry_type", "received_amount", "confirmed"))
        self.assertEqual(rows[0], (deposit.pk, "receipt", Decimal("2000"), True), "已確認實收不動")
        self.assertEqual([row[1] for row in rows], ["receipt", "refund"], "尾款應收清除、退款紀錄保留")
        self.assertEqual(order.get_status_display(), "已取消／已退款")

    def test_forfeit_all_is_labelled_cancelled_only(self):
        order = self.make_order(source_type="store", source=self.staff, deposit_amount=Decimal("2000"),
                                cash_receivable_v2=True)
        self.confirm_deposit(order)
        order.request_cancellation("測試人員", "")
        order.complete_refund("測試人員", Decimal("2000"), date(2026, 9, 5), "", forfeit_reason="客戶放棄")
        order.refresh_from_db()
        self.assertEqual((order.status, order.refund_amount), (CANCELLED, 0))
        self.assertEqual(order.get_status_display(), "已取消")

    def test_confirmed_payout_and_manual_rows_are_never_cleared(self):
        order = self.platform_order()
        payout = order.payment_records.get(system_key="platform_disbursement")
        payout.received_amount = Decimal("80000")
        payout.received_on = date(2026, 9, 10)
        payout.confirmed = True
        payout.save()
        manual = PaymentRecord.objects.create(order=order, item_name="人工備忘", expected_amount=Decimal("500"))
        SalesOrder.objects.filter(pk=order.pk).update(status=CANCELLED)
        removed = clear_cancelled_receivables(order, actor_name="測試人員")
        self.assertTrue(PaymentRecord.objects.filter(pk__in=[payout.pk, manual.pk]).count() == 2)
        self.assertNotIn(payout.pk, removed)
        self.assertNotIn(manual.pk, removed)

    def test_not_cancelled_order_is_untouched(self):
        order = self.make_order(source_type="store", source=self.staff)
        self.assertEqual(clear_cancelled_receivables(order, actor_name="測試人員"), [])
        self.assertEqual(self.keys(order), ["balance", "deposit"])

    def test_command_dry_run_apply_and_rollback(self):
        order = self.make_order(source_type="store", source=self.staff, deposit_amount=Decimal("2000"),
                                cash_receivable_v2=True)
        before = {row["id"]: row for row in order.payment_records.values()}
        # 模擬改版前就已取消、還留著應收列的訂單。
        SalesOrder.objects.filter(pk=order.pk).update(status=CANCELLED)
        out = StringIO()
        call_command("clear_cancelled_receivables", stdout=out)
        self.assertIn("符合：1 張已取消訂單、2 筆", out.getvalue())
        self.assertIn("dry-run：未寫入", out.getvalue())
        self.assertEqual(len(before), order.payment_records.count())

        call_command("clear_cancelled_receivables", "--apply", stdout=StringIO())
        self.assertEqual(self.keys(order), [])
        self.assertTrue(OrderChange.objects.filter(order=order, reason__startswith=CLEAR_REASON).exists())

        call_command("clear_cancelled_receivables", "--rollback", stdout=StringIO())
        after = {row["id"]: row for row in order.payment_records.values()}
        self.assertEqual(set(after), set(before), "以原編號重建")
        for pk, row in before.items():
            self.assertEqual({k: v for k, v in after[pk].items() if k != "updated_at"},
                             {k: v for k, v in row.items() if k != "updated_at"})
        self.assertTrue(order.events.filter(event_type="cancelled_receivables_restored").exists())
