"""1.62.2：分期客戶尾款含選號等其他費用、沒收訂金不留收款日、補助「無」不顯示新舊車主、變更說明選填。"""
from datetime import date
from decimal import Decimal

import pypdfium2 as pdfium
from django.test import TestCase
from django.urls import reverse

from sales.models import OtherFeeLine, SalesOrder
from sales.services.customer_receivable import default_customer_balance
from sales.services.order_contract_pdf import build_order_contract_pdf
from sales.tests import test_completed_order_corrections as correction_tests


def pdf_text(pdf_bytes):
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        return "".join(page.get_textpage().get_text_range() for page in document)
    finally:
        document.close()


class OrderFixes1622Tests(TestCase):
    # 借用完成後修正測試的建立訂單與送出表單工具，但不繼承它的測試。
    setUpTestData = classmethod(correction_tests.CompletedOrderCorrectionTests.setUpTestData.__func__)
    setUp = correction_tests.CompletedOrderCorrectionTests.setUp
    order = correction_tests.CompletedOrderCorrectionTests.order
    payload = correction_tests.CompletedOrderCorrectionTests.payload
    post = correction_tests.CompletedOrderCorrectionTests.post
    assert_saved = correction_tests.CompletedOrderCorrectionTests.assert_saved

    def installment_order(self, **overrides):
        data = dict(
            payment_type="installment", vehicle_price=75000, actual_balance=76200, plate_insurance_fee=0,
            installment_company="測試分期", installment_periods=24, installment_monthly=Decimal("3125"),
            installment_amount=75000, deposit_amount=0, status=SalesOrder.Status.ALLOCATION_PENDING,
            registration_date=None, cash_receivable_v2=True,
        )
        data.update(overrides)
        order = self.order(**data)
        OtherFeeLine.objects.create(order=order, name="選號", amount=1200)
        return SalesOrder.objects.get(pk=order.pk)

    def test_installment_customer_pays_other_fees_like_plate_selection(self):
        order = self.installment_order()
        self.assertEqual(default_customer_balance(order), Decimal("1200"))
        order.deposit_amount = 200
        self.assertEqual(default_customer_balance(order), Decimal("1000"))

    def test_no_deposit_clears_deposit_date(self):
        order = self.installment_order()
        self.assertIsNone(order.deposit_date, "訂金 0 時不留預設的今天日期")
        order.deposit_amount = 500
        order.deposit_date = date(2026, 10, 9)
        order.actual_balance = order.calculate_balance()
        order.save()
        order.refresh_from_db()
        self.assertEqual(order.deposit_date, date(2026, 10, 9))

    def test_contract_shows_no_owner_relation_without_subsidy(self):
        from sales.models import PrintCompany
        company, _ = PrintCompany.objects.update_or_create(key="home", defaults=dict(legal_name="測試機車行", tax_id="12345678", address="測試地址", phone="02-1234"))
        order = self.installment_order(is_trade_in_subsidy=False, old_owner_same_as_owner=False)
        order.print_company = company
        order.print_company_snapshot = {"legal_name": "測試機車行", "tax_id": "12345678", "address": "測試地址", "phone": "02-1234"}
        order.save(update_fields=["print_company", "print_company_snapshot"])
        text = pdf_text(build_order_contract_pdf(order))
        self.assertNotIn("不同人", text)
        self.assertNotIn("舊車主姓名", text)
        self.assertIn("訂金收款日", text)

    def test_change_reason_is_optional_on_order_edit(self):
        order = self.order()
        response = self.post(order, change_reason="", note="不寫說明也能存")
        self.assert_saved(response, order)
        self.assertEqual(order.note, "不寫說明也能存")
        page = self.client.get(reverse("order_edit", args=[order.pk]))
        self.assertContains(page, "變更說明（選填）")
