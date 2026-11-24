"""T-313：四處金額顯示改成負號在金額符號前（−$1,000，與 T-312 同一個負號字元 U+2212）、有千分位。只改顯示，不改金額計算。

1. 訂購合約模板（contract_print.html；目前路由改印 PDF，模板未被 view 使用）的配件金原本印「面額 1000 元，實際折抵 -600 元」。
2. 訂單匯出「配件」欄的配件金原本印「-1,000，實際折抵 -600」；這欄回匯時只能看、不解析，新格式原樣匯回不得產生變更或忽略提示。
3. 配件主檔清單一般配件的售價、工資、參考成本原本用 floatformat:0，沒有千分位（$12345）。
4. 統一撥款對帳的差額原本印「$-608」。

其他模組的 TestCase 只 import 模組、借用輔助方法，避免整個測試類別被這個模組再收一次、重跑一遍。
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import AccessoryLine, AccessoryProduct
from sales.order_exchange import reimport
from sales.tests import test_order_bulk_update_t232 as t232
from sales.tests import test_order_lifecycle as lifecycle
from sales.tests import test_payout_reconciliation_t96 as t96
from sales.tests.test_accessory_credit_t305 import AccessoryCreditBase
from sales.tests.test_finance_ledger import FinanceLedgerTestBase

MINUS = "−"  # U+2212，與 signed_money、reconciliation.js 相同


class CreditMoneyFormatTests(AccessoryCreditBase):
    def setUp(self):
        super().setUp()
        self.add_line(self.helmet)  # 配件小計 600，配件金面額 1,000 只折 600
        self.add_line(self.credit)
        self.order = self.reload()

    def login(self):
        self.client.force_login(get_user_model().objects.create_superuser("t313-root", password="testing-only-123"))

    def contract_html(self, order):
        # /orders/<pk>/contract/ 現在回 build_order_contract_pdf 的 PDF，contract_print.html 沒有 view 在用；直接渲染模板驗證。
        from django.template.loader import render_to_string

        return render_to_string("sales/contract_print.html", {"order": order})

    def test_contract_print_credit_puts_minus_before_dollar(self):
        html = self.contract_html(self.order)
        self.assertIn(f"配件金 1000（配件金，面額 $1,000，實際折抵 {MINUS}$600）", html)
        self.assertNotIn("-600", html)

    def test_contract_print_fully_voided_credit_shows_zero_without_sign(self):
        AccessoryLine.objects.filter(order=self.order, is_credit=False).delete()
        html = self.contract_html(self.reload())
        self.assertIn("實際折抵 $0）", html)
        self.assertNotIn(f"{MINUS}$0", html)

    def test_contract_print_regular_accessory_unchanged(self):
        self.assertIn("安全帽 × 1（加購，600 元）", self.contract_html(self.order))

    def test_export_credit_puts_minus_before_dollar(self):
        from sales.order_exchange.columns import _accessories

        self.assertEqual(_accessories(self.order), f"安全帽 500；配件金 1000（配件金）{MINUS}$1,000，實際折抵 {MINUS}$600")

    def test_export_fully_voided_credit_shows_zero_without_sign(self):
        from sales.order_exchange.columns import _accessories

        AccessoryLine.objects.filter(order=self.order, is_credit=False).delete()
        self.assertEqual(_accessories(self.reload()), f"配件金 1000（配件金）{MINUS}$1,000，實際折抵 $0")

    def test_accessory_product_list_regular_money_has_thousands_separator(self):
        AccessoryProduct.objects.create(name="整流罩", sale_price=Decimal("12345"), labor_fee=Decimal("1500"), cost=Decimal("9800"))
        self.login()
        page = self.client.get(reverse("accessory_product_list"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, '<td data-label="售價">$12,345</td>', html=False)
        self.assertContains(page, '<td data-label="工資">$1,500</td>', html=False)
        self.assertContains(page, '<td data-label="參考成本">$9,800</td>', html=False)
        self.assertContains(page, "折抵 $1,000")  # 配件金欄照 T-312


class ExportCreditReimportTests(TestCase):
    """匯出→回匯（T-232）：「配件」欄只能看、不解析；新格式原樣匯回不產生變更，也不列忽略。"""
    setUp_base = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order
    _base = t232.OrderBulkUpdateTests
    export_book, set_cell, upload, uploaded_batch = _base.export_book, _base.set_cell, _base.upload, _base.uploaded_batch
    preview, apply, row_of = _base.preview, _base.apply, _base.row_of

    def setUp(self):
        self._base.setUp(self)
        self.order, _vehicle = self.make_order()
        credit = AccessoryProduct.objects.create(name="配件金 1000", kind="credit", sale_price=Decimal("-1000"))
        helmet = AccessoryProduct.objects.create(name="安全帽", sale_price=Decimal("500"), labor_fee=Decimal("100"))
        for product in (helmet, credit):
            AccessoryLine.objects.create(order=self.order, accessory_product=product, name=product.name, quantity=1,
                                         line_type="purchase", amount=product.sale_price, labor_fee=product.labor_fee,
                                         is_credit=product.is_credit)

    def lines(self):
        return list(AccessoryLine.objects.filter(order=self.order).order_by("pk").values_list("name", "amount", "labor_fee", "is_credit"))

    def test_unchanged_export_reimports_without_changes_or_notices(self):
        book = self.export_book(["accessories", "note"])
        cell = next(row for row in book["訂單"].iter_rows(min_row=3, values_only=True) if row[0] == self.order.pk)
        self.assertIn(f"{MINUS}$1,000，實際折抵 {MINUS}$600", " ".join(str(value) for value in cell))
        before = self.lines()
        item = self.row_of(self.preview(self.uploaded_batch(book)), self.order)
        self.assertEqual((item["errors"], item["fields"], item["ignored"]), ([], [], []))
        self.assertEqual(self.lines(), before)

    def test_edited_accessory_cell_is_ignored_and_not_written(self):
        book = self.export_book(["accessories", "note"])
        self.set_cell(book, self.order, "accessories", "安全帽 500；配件金 1000（配件金）−$2,000，實際折抵 −$600")
        before = self.lines()
        batch = self.uploaded_batch(book)
        item = self.row_of(self.preview(batch), self.order)
        self.assertEqual(item["fields"], [])
        self.assertEqual(item["ignored"], [{"label": "配件", "reason": reimport.IGNORED_READONLY}])
        self.apply(batch)
        self.assertEqual(self.lines(), before)


class ReconciliationDifferenceFormatTests(FinanceLedgerTestBase):
    _base = t96.PayoutReconciliationTests
    setUp, installment_order, payout, listed, post = (
        _base.setUp, _base.installment_order, _base.payout, _base.listed, _base.post)

    def test_negative_difference_puts_minus_before_dollar(self):
        row = self.payout(self.installment_order())
        self.post(row, 76000)
        response, _ids = self.listed()
        self.assertContains(response, f"<strong>{MINUS}$608</strong>", html=False)
        self.assertNotContains(response, "$-608")

    def test_positive_difference_keeps_plus_and_thousands_separator(self):
        row = self.payout(self.installment_order())
        self.post(row, 77608)
        response, _ids = self.listed()
        self.assertContains(response, "<strong>+$1,000</strong>", html=False)

