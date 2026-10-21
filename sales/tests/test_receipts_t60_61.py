"""收支頁收款區（使用者 2026-10-21 T-60、T-61）。

T-60：收款明細不列未收的系統尾款列，尾款只在「交車與收尾款」登記；交車時收了尾款才出現在收款明細。
T-61：收款區只留表頭、收款列與新增收款；說明、應收摘要與「收款明細」小標都拿掉。
"""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from sales.tests import test_payment_ledger as ledger


class ReceiptAreaTests(TestCase):
    setUpTestData = classmethod(ledger.PaymentLedgerTests.setUpTestData.__func__)
    setUp = ledger.PaymentLedgerTests.setUp

    def receipts(self):
        page = self.client.get(reverse("order_detail", args=[self.order.pk]), {"tab": "finance"}).content.decode()
        section = page.split('id="finance-receipts"', 1)[1].split("</details>", 1)[0]
        return page, section

    def test_receipt_area_is_only_head_rows_and_add_button(self):
        page, section = self.receipts()
        for gone in ("僅預設訂金", "data-receipt-summary", "客戶應收", "客戶尚欠", "分期公司應收", "客戶溢收", "已登記待確認",
                     "已確認的收款會鎖定", "<h3>收款明細</h3>", "應收尾款 $"):
            self.assertNotIn(gone, section)
        self.assertIn('<div class="receipt-list-head" aria-hidden="true">', section)
        self.assertIn('id="add-payment"', section)

    def test_unpaid_balance_is_hidden_until_collected(self):
        balance = self.order.payment_records.get(system_key="balance")
        _page, section = self.receipts()
        rows = section.split('id="payment-records"', 1)[1].split('<template id="payment-empty-row"', 1)[0]
        self.assertNotRegex(rows, rf'name="payments-\d+-id" value="{balance.pk}"')
        self.assertIn(f'value="{balance.pk}"', section.split("data-payment-expectation", 1)[1])
        balance.received_amount = balance.expected_amount
        balance.received_on = date(2026, 9, 21)
        balance.payment_method = "匯款"
        balance.confirmed = True
        balance.save()
        _page, section = self.receipts()
        rows = section.split('id="payment-records"', 1)[1].split('<template id="payment-empty-row"', 1)[0]
        self.assertRegex(rows, rf'name="payments-\d+-id" value="{balance.pk}"')
