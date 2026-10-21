"""收款明細欄位精簡（使用者 2026-10-21 T-54：「保留"向客戶收取手續費"，其他直接刪除」）。

刷卡本金、銀行實扣手續費、收款帳戶、收款證明、備註不在收支頁收款表單；資料庫欄位與既有值、檔案保留，
儲存收款列不會清掉。向客戶收取手續費只在收款方式為刷卡時顯示，照舊加總成刷卡手續費收入；
刷卡手續費支出照舊由銀行實扣手續費加總（以後為 0）。
"""
import re
import tempfile
from decimal import Decimal

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from sales.forms import DeliveryPaymentForm, PaymentRecordForm
from sales.models import OrderOperationsProfile, PaymentRecord
from sales.services.order_workspace import payment_formset_for
from sales.tests import test_payment_ledger as ledger

REMOVED = ("card_principal", "bank_card_fee", "receiving_account", "proof", "note")


class PaymentFormFieldsTests(TestCase):
    def test_only_customer_card_fee_remains(self):
        self.assertIn("card_fee_charged", PaymentRecordForm.base_fields)
        for name in REMOVED:
            self.assertNotIn(name, PaymentRecordForm.base_fields)
        # 交車「尾款收妥」不在這次範圍，收款帳戶、證明、備註照舊。
        for name in ("receiving_account", "proof", "note"):
            self.assertIn(name, DeliveryPaymentForm.base_fields)

    def test_card_fee_still_requires_card_method(self):
        form = PaymentRecordForm(data={"item_name": "尾款", "received_amount": "31500", "card_fee_charged": "1500",
                                       "payment_method": "現金"})
        self.assertFalse(form.is_valid())
        self.assertIn("付款方式必須選擇「刷卡」", form.errors["payment_method"][0])


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PaymentRowTests(TestCase):
    setUpTestData = classmethod(ledger.PaymentLedgerTests.setUpTestData.__func__)
    setUp = ledger.PaymentLedgerTests.setUp
    payload = ledger.PaymentLedgerTests.payload
    add_row = ledger.PaymentLedgerTests.add_row
    post_operations = ledger.PaymentLedgerTests.post_operations

    def card_payment(self, **values):
        payment = PaymentRecord.objects.create(
            order=self.order, item_name="刷卡收款", received_amount=Decimal("31500"), payment_method="刷卡",
            card_principal=Decimal("30000"), card_fee_charged=Decimal("1500"), bank_card_fee=Decimal("900"),
            receiving_account="公司帳戶", note="舊備註", **values,
        )
        payment.proof.save("proof.pdf", ContentFile(b"%PDF-1.4 test"), save=True)
        return payment

    def page(self):
        return self.client.get(reverse("order_detail", args=[self.order.pk]), {"tab": "finance"}).content.decode()

    def test_saving_keeps_hidden_values_and_proof(self):
        payment = self.card_payment()
        proof_name = payment.proof.name
        payload = self.payload()
        row = next(form for form in payment_formset_for(self.order) if form.instance.pk == payment.pk)
        payload[row.add_prefix("card_fee_charged")] = "1600"
        response = self.post_operations(payload)
        self.assertEqual(response.status_code, 200, response.content)
        payment.refresh_from_db()
        self.assertEqual(payment.card_fee_charged, Decimal("1600"))
        self.assertEqual((payment.card_principal, payment.bank_card_fee, payment.receiving_account, payment.note, payment.proof.name),
                         (Decimal("30000"), Decimal("900"), "公司帳戶", "舊備註", proof_name))
        self.assertTrue(payment.proof.storage.exists(proof_name))
        profile = OrderOperationsProfile.objects.get(order=self.order)
        self.assertEqual((profile.card_fee_income, profile.card_fee_expense), (Decimal("1600"), Decimal("900")))

    def test_new_row_saves_customer_card_fee(self):
        payload = self.add_row(self.payload(), payment_method="刷卡", card_fee_charged="800", confirmed="")
        self.assertEqual(self.post_operations(payload).status_code, 200)
        created = self.order.payment_records.get(item_name="第二筆收款")
        self.assertEqual((created.card_fee_charged, created.bank_card_fee, created.card_principal), (Decimal("800"), 0, 0))
        self.assertEqual(OrderOperationsProfile.objects.get(order=self.order).card_fee_income, Decimal("800"))

    def test_row_layout(self):
        self.card_payment(confirmed=True, confirmed_by="店員", confirmed_at=timezone.now())
        page = self.page()
        rows = page.split('id="payment-records"', 1)[1]
        self.assertNotIn("更多資料", page)
        self.assertNotIn("receipt-more", page)
        for name in REMOVED:
            self.assertNotRegex(rows, rf'name="payments-\d+-{name}"')
        # 刷卡列顯示手續費；其他方式（含新增列範本）收起來。
        fees = re.findall(r'<div class="receipt-card-fee" data-card-fee( hidden)?>', rows)
        self.assertIn("", fees)
        self.assertIn(" hidden", fees)
        self.assertIn("向客戶收取手續費", rows)
        self.assertIn('<div class="receipt-actions">', rows)
        self.assertIn('aria-label="刪除此筆收款">刪除</button>', rows)
        self.assertRegex(rows, r'<p class="receipt-meta">\s*<span>確認：')
        self.assertIn("查看收款附件", rows)
        self.assertIn("登記錯的可按列尾「刪除」", page)
