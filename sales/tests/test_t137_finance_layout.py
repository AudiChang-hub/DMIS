"""T-137（使用者 2026-11-09 測試）。

p1：SO20261107-91529C 收入與支出的「尾款」顯示 26,300（總價－約定訂金），下方收款進度「還要收」是 16,300
（另外收了 10,000）。兩個數字不同源；尾款改成和「還要收」同一個 payment_summary.delivery_due。
p7：收入與支出由上而下 ①成交與車行結算 ②內部折扣／牌險差異 ③收款 ④尾款 ⑤收支總覽 ⑥領牌試算 ⑦收入／支出；
「成交金額與尾款試算」與「尾款計算」那一列拿掉。"""
from datetime import date
from decimal import Decimal

from django.urls import reverse

from sales.models import PaymentRecord, SalesOrder
from sales.services.operations_sync import sync_order_operations
from sales.services.payment_summary import payment_summary
from sales.tests import test_finance_ledger as ledger


class FinanceLayoutTests(ledger.FinanceLedgerTestBase):
    setUp = ledger.FinanceStepPageTests.setUp
    finance_panel = ledger.FinanceStepPageTests.finance_panel

    def store_order(self, **kwargs):
        order = self.make_order(source_type="store", source=self.staff, cash_receivable_v2=True,
                                deposit_amount=Decimal("50000"), **kwargs)
        sync_order_operations(order.pk)
        PaymentRecord.objects.filter(order=order, system_key="deposit").update(
            received_amount=Decimal("50000"), received_on=date(2026, 11, 2), payment_method="匯款", confirmed=True)
        return SalesOrder.objects.get(pk=order.pk)

    def test_balance_headline_equals_amount_still_to_collect(self):
        order = self.store_order()
        PaymentRecord.objects.create(order=order, item_name="收款", received_amount=Decimal("10000"),
                                     received_on=date(2026, 11, 3), payment_method="匯款", confirmed=True)
        order = SalesOrder.objects.get(pk=order.pk)
        summary = payment_summary(order)
        contract_balance = order.customer_balance_due
        self.assertEqual(summary["delivery_due"], contract_balance - 10000)
        _page, finance = self.finance_panel(order)
        balance = finance.split('aria-label="尾款"', 1)[1].split("</section>", 1)[0]
        due = f'{summary["delivery_due"]:,.0f}'
        self.assertIn(f'<span>尾款</span><strong>$<b data-receipt-value="delivery_due">{due}</b>', balance)
        self.assertIn(f'<span>＝ 還要收</span><strong>$<b data-receipt-value="delivery_due">{due}</b>', balance)
        self.assertNotIn(f"{contract_balance:,.0f}", balance)

    def test_finance_sections_follow_requested_order_without_duplicates(self):
        order = self.make_order(registration_calculated_total=Decimal("2000"))
        _page, finance = self.finance_panel(order)
        markers = ['id="workspace-finance-settlement"', 'id="internal-discount-title"', 'id="finance-receipts"',
                   'aria-label="尾款"', 'id="workspace-finance-summary"', 'aria-label="領牌試算"', "data-finance-ledger"]
        positions = [finance.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))
        settlement = finance.split('id="workspace-finance-settlement"', 1)[1].split("</section>", 1)[0]
        self.assertIn("折扣後成交總額", settlement)
        self.assertIn("data-dealer-settlement", finance.split('id="workspace-finance-settlement"', 1)[1].split('id="internal-discount-title"', 1)[0])
        for removed in ("成交金額與尾款試算", "尾款計算", "車價依據", "money-list__payments"):
            self.assertNotIn(removed, finance)

    def test_autosave_refreshes_settlement_block(self):
        order = self.make_order()
        sync_order_operations(order.pk)
        from sales.services import order_workspace
        from django.test import RequestFactory
        request = RequestFactory().post("/")
        request.user = self.admin
        payload = order_workspace.saved(request, SalesOrder.objects.get(pk=order.pk)).content.decode()
        self.assertIn("workspace-finance-settlement", payload)
