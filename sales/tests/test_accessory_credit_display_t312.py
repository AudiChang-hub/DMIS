"""T-312：配件金的金額顯示（只改顯示，不改金額計算）。

1. 訂單總覽與訂單頁的配件金列原本印「$-1,000」，改成負號在金額符號前「−$1,000」。
2. 配件主檔清單的配件金原本印「折抵 $1000」，補上千分位「折抵 $1,000」。
3. 配件金把配件小計折到 0 元時，訂單頁收款摘要（應收怎麼算）的「配件」列原本整列消失，改為保留並註明折抵多少。
"""
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import AccessoryLine, AccessoryProduct, PaymentRecord, SalesOrder
from sales.tests import test_order_steps as steps
from sales.tests.test_accessory_credit_t305 import AccessoryCreditBase


class CreditDisplayTests(AccessoryCreditBase):
    def setUp(self):
        super().setUp()
        self.add_line(self.helmet)  # 配件小計 600，配件金面額 1,000 只折 600
        self.add_line(self.credit)
        self.order = self.reload()

    def login(self):
        self.client.force_login(get_user_model().objects.create_superuser("t312-root", password="testing-only-123"))

    def read_only_order_page(self, order):
        # 訂單頁的唯讀摘要（「配件與需求明細」）只在不能改內容時出現（沒修改權限、已鎖定）；可改時換成自動儲存表單。
        self.login()
        with mock.patch.object(SalesOrder, "can_edit_content", new_callable=mock.PropertyMock, return_value=False):
            page = self.client.get(reverse("order_detail", args=[order.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "配件與需求明細")
        return page

    def test_overview_credit_row_puts_minus_before_dollar(self):
        from sales.services.order_overview import build_order_overview

        table = next(table for table in build_order_overview(self.order)["tables"] if table["key"] == "accessories")
        row = next(row for row in table["rows"] if row[0] == "配件金 1000")
        self.assertEqual((row[3], row[5]), ("−$1,000", "−$600"))

    def test_overview_regular_rows_unchanged(self):
        from sales.services.order_overview import build_order_overview

        table = next(table for table in build_order_overview(self.order)["tables"] if table["key"] == "accessories")
        row = next(row for row in table["rows"] if row[0] == "安全帽")
        self.assertEqual((row[3], row[4], row[5]), ("$500", "$100", "$600"))

    def test_order_detail_credit_line_puts_minus_before_dollar(self):
        page = self.read_only_order_page(self.order)
        self.assertContains(page, "實際折抵 −$600")
        self.assertContains(page, "<strong>−$600</strong>", html=False)
        self.assertNotContains(page, "$-600")

    def test_fully_voided_credit_shows_zero_without_sign(self):
        from sales.models import AccessoryLine
        from sales.services.order_overview import build_order_overview

        AccessoryLine.objects.filter(order=self.order, is_credit=False).delete()
        order = self.reload()
        table = next(table for table in build_order_overview(order)["tables"] if table["key"] == "accessories")
        row = next(row for row in table["rows"] if row[0] == "配件金 1000")
        self.assertEqual(row[5], "$0")
        section = self.read_only_order_page(order).content.decode().split("配件與需求明細", 1)[1].split("</section>", 1)[0]
        self.assertIn("實際折抵 $0", section)
        self.assertIn("<strong>$0</strong>", section)
        self.assertNotIn("$-0", section)
        self.assertNotIn("−$0", section)

    def test_accessory_product_list_credit_has_thousands_separator(self):
        AccessoryProduct.objects.create(name="配件金 12345", kind="credit", sale_price=Decimal("-12345"))
        self.login()
        page = self.client.get(reverse("accessory_product_list"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "折抵 $1,000")
        self.assertContains(page, "折抵 $12,345")
        self.assertNotContains(page, "折抵 $1000")


class CreditLedgerRowTests(AccessoryCreditBase):
    """3. 配件金把配件小計折到 0 元時，收款摘要（應收怎麼算）的「配件」列保留並註明折抵多少；金額與應收不變。"""

    def accessory_row(self, order):
        from sales.services.payment_summary import balance_breakdown

        breakdown = balance_breakdown(order)
        return breakdown, next((row for row in breakdown["charges"] if row["label"] == "配件"), None)

    def test_row_kept_when_credit_covers_whole_subtotal(self):
        mat = AccessoryProduct.objects.create(name="腳踏墊", sale_price=Decimal("400"))
        self.add_line(self.helmet)  # 600
        self.add_line(mat)          # 400，小計 1,000 全被配件金折掉
        before_total = self.accessory_row(self.reload())[0]["total"]
        self.add_line(self.credit)
        order = self.reload()
        self.assertEqual(order.accessory_total, Decimal("0"))
        breakdown, row = self.accessory_row(order)
        self.assertIsNotNone(row)
        self.assertEqual((row["amount"], row["note"]), (Decimal("0"), "配件金折抵 $1,000"))
        # 金額計算不變：總價恰好少配件金實際折抵的 1,000，費用合計仍是各列加總。
        self.assertEqual(breakdown["total"], before_total - Decimal("1000"))
        self.assertEqual(breakdown["charges_total"], sum((item["amount"] for item in breakdown["charges"]), Decimal("0")))

    def test_row_kept_with_void_note(self):
        self.add_line(self.helmet)  # 600，配件金 1,000 折 600、400 作廢
        self.add_line(self.credit)
        _breakdown, row = self.accessory_row(self.reload())
        self.assertEqual((row["amount"], row["note"]), (Decimal("0"), "配件金折抵 $600，$400 作廢"))

    def test_credit_only_order_keeps_row(self):
        self.add_line(self.credit)
        _breakdown, row = self.accessory_row(self.reload())
        self.assertEqual((row["amount"], row["note"]), (Decimal("0"), "配件金折抵 $0，$1,000 作廢"))

    def test_no_accessories_no_credit_has_no_row(self):
        _breakdown, row = self.accessory_row(self.reload())
        self.assertIsNone(row)

    def test_partial_credit_row_unchanged(self):
        self.add_line(self.helmet, quantity=2)  # 1,200 − 1,000 ＝ 200，原本就會列，不加註
        self.add_line(self.credit)
        _breakdown, row = self.accessory_row(self.reload())
        self.assertEqual((row["amount"], row.get("note", "")), (Decimal("200"), ""))


class CreditLedgerPageTests(TestCase):
    """3. 訂單頁交車步驟「應收怎麼算」實際畫面：配件列保留、註明折抵、配件金子項印 −$1,000，應收不變。"""
    setUp = steps.OrderStepTests.setUp
    make_order = steps.OrderStepTests.make_order
    registered_v2 = steps.OrderStepTests.registered_v2

    def exact_order(self, *, credit, accessory=True):
        order, _vehicle = self.registered_v2(deposit=Decimal("4800"))
        if accessory:
            AccessoryLine.objects.create(order=order, name="後保桿", quantity=1, amount=Decimal("1000"))
        if credit:
            product = AccessoryProduct.objects.create(name="配件金 1000", kind="credit", sale_price=Decimal("-1000"))
            AccessoryLine.objects.create(order=order, accessory_product=product, name=product.name, amount=Decimal("-1000"), is_credit=True)
        order = SalesOrder.objects.get(pk=order.pk)
        balance = order.calculate_balance()
        SalesOrder.objects.filter(pk=order.pk).update(actual_balance=balance, calculated_balance=balance)
        PaymentRecord.objects.filter(order=order, system_key="deposit").update(expected_amount=Decimal("4800"), received_amount=Decimal("4800"), confirmed=True)
        from sales.services.operations_sync import sync_order_operations
        sync_order_operations(order.pk)
        return SalesOrder.objects.get(pk=order.pk)

    def ledger(self, order):
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        delivery = page.split('id="panel-delivery"', 1)[1].split('id="panel-subsidy"', 1)[0]
        return delivery.split('class="balance-ledger"', 1)[1].split("</section>", 1)[0]

    def test_ledger_keeps_accessory_row_at_zero_with_credit_note(self):
        from sales.services.payment_summary import balance_breakdown, payment_summary

        without = self.exact_order(credit=False)
        due_without = balance_breakdown(without)["due"]
        order = self.exact_order(credit=True)
        b = balance_breakdown(order)
        self.assertTrue(b["exact"], b)
        # 應收照舊：恰好少配件金折抵的 1,000，且與交車判斷同一個數字。
        self.assertEqual(b["due"], due_without - Decimal("1000"))
        self.assertEqual(b["due"], payment_summary(order)["delivery_due"])
        ledger = self.ledger(order)
        self.assertIn("<dt>配件", ledger)
        self.assertIn("（配件金折抵 $1,000）", ledger)
        self.assertIn("−$1,000", ledger)
        self.assertNotIn("$-1,000", ledger)

    def test_ledger_without_accessories_has_no_accessory_row(self):
        from sales.services.payment_summary import balance_breakdown

        order = self.exact_order(credit=False, accessory=False)
        self.assertTrue(balance_breakdown(order)["exact"])
        ledger = self.ledger(order)
        self.assertIn("<dt>車價", ledger)
        self.assertNotIn("<dt>配件", ledger)
