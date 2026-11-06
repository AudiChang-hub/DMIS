"""T-120（使用者 2026-11-05）：
p10 交車「應收怎麼算」要扣掉訂金以外的已確認收款，收款列自動儲存後跟著換新（前後端同一份 payment_summary）；
p15 交車頁不收尾款時（應收 0、已交車）也顯示應收，含 0 元；尾款計算卡列出收款進度；
p9 收款明細一筆一橫列（收款對象獨立一欄）。"""
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.test import RequestFactory, TestCase
from django.urls import reverse

from sales.models import PaymentRecord, SalesOrder
from sales.services import order_workspace
from sales.services.payment_summary import payment_summary
from sales.tests import test_order_steps as steps
from sales.tests.test_delivery_balance_t73 import delivery_panel


class DeliveryReceivableTests(TestCase):
    setUp = steps.OrderStepTests.setUp
    make_order = steps.OrderStepTests.make_order
    registered_v2 = steps.OrderStepTests.registered_v2

    def with_receipts(self, *amounts, deposit=Decimal("5000")):
        order, _vehicle = self.registered_v2(deposit=deposit)
        PaymentRecord.objects.filter(order=order, system_key="deposit").update(received_amount=deposit, confirmed=True)
        for index, amount in enumerate(amounts):
            PaymentRecord.objects.create(order=order, item_name="分批匯款", expected_amount=0, received_amount=amount,
                                         received_on=date(2026, 10, 27 + index), payment_method="匯款", confirmed=True)
        return SalesOrder.objects.get(pk=order.pk)

    def page(self, order):
        self.client.force_login(self.user)
        return self.client.get(reverse("order_detail", args=[order.pk])).content.decode()

    def test_other_confirmed_receipts_are_listed_and_deducted(self):
        order = self.with_receipts(Decimal("30000"), Decimal("30000"))
        summary = payment_summary(order)
        expected_due = summary["customer_expected"] - Decimal("65000")
        self.assertEqual(summary["delivery_due"], max(expected_due, Decimal("0")))
        delivery = delivery_panel(self.page(order))
        self.assertIn("<dt>已收訂金</dt><dd>−$5,000</dd>", delivery)
        self.assertIn("<dt>其他已收款</dt><dd>−$60,000</dd>", delivery)

    def test_autosave_payload_refreshes_delivery_ledger(self):
        order = self.with_receipts()
        request = RequestFactory().get("/")
        request.user = self.user
        before = json.loads(order_workspace.saved(request, order).content)
        self.assertNotIn("其他已收款", before["delivery_ledger_html"])
        PaymentRecord.objects.create(order=order, item_name="分批匯款", expected_amount=0, received_amount=Decimal("30000"),
                                     received_on=date(2026, 10, 27), payment_method="匯款", confirmed=True)
        after = json.loads(order_workspace.saved(request, order).content)
        self.assertEqual(Decimal(after["delivery_due"]), payment_summary(order)["delivery_due"])
        self.assertEqual(Decimal(before["delivery_due"]) - Decimal(after["delivery_due"]), Decimal("30000"))
        self.assertIn("其他已收款", after["delivery_ledger_html"])
        self.assertIn("data-balance-ledger", after["delivery_ledger_html"])
        script = Path("static/js/order-workspace.js").read_text(encoding="utf-8")
        self.assertIn("payload.delivery_ledger_html", script)
        self.assertIn("new CustomEvent('delivery:due')", script)
        form_script = Path("static/js/delivery-form.js").read_text(encoding="utf-8")
        self.assertIn('fieldset.addEventListener("delivery:due", sync)', form_script)
        self.assertNotIn("const due = Number(fieldset.dataset.deliveryDue", form_script)

    def test_zero_due_still_shows_receivable_before_and_after_delivery(self):
        order, _vehicle = self.registered_v2()
        total = payment_summary(order)["customer_expected"]
        PaymentRecord.objects.filter(order=order, system_key="deposit").update(received_amount=total, confirmed=True)
        order = SalesOrder.objects.get(pk=order.pk)
        delivery = delivery_panel(self.page(order))
        self.assertNotIn('id="delivery-balance"', delivery)
        self.assertIn("data-delivery-overview", delivery)
        self.assertIn('data-delivery-due-amount>$0</strong>', delivery)
        self.assertIn("應收 $0：客戶款項已收清，不用再收尾款。", delivery)
        SalesOrder.objects.filter(pk=order.pk).update(status=SalesOrder.Status.DELIVERED_DOCS_PENDING)
        delivered = delivery_panel(self.page(SalesOrder.objects.get(pk=order.pk)))
        self.assertIn("已交車，客戶款項已收清。", delivered)

    def test_fee_card_lists_receipt_progress(self):
        order = self.with_receipts(Decimal("30000"))
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "finance"}).content.decode()
        summary = payment_summary(order)
        progress = page.split("data-receipt-progress", 1)[1].split("</div>\n        </div>", 1)[0]
        self.assertIn(f'data-receipt-value="customer_received">{summary["customer_received"]:,.0f}<', progress)
        self.assertIn(f'data-receipt-value="delivery_due">{summary["delivery_due"]:,.0f}<', progress)

    def test_receipt_rows_are_single_line_with_kind_column(self):
        order = self.with_receipts(Decimal("30000"))
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "finance"}).content.decode()
        self.assertIn("<span>收款項目</span><span>收款對象</span><span>實收金額</span>", page)
        row = page.split("data-payment-row", 2)[1]
        self.assertIn('<div class="receipt-kind">', row)
        name = row.split('<div class="receipt-name">', 1)[1].split('<div class="receipt-kind">', 1)[0]
        self.assertNotIn("receipt_kind", name)
