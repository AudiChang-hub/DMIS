"""新舊車主不同人聲明書的列印入口（使用者 2026-11-03 簡報第 5 頁）。

原本補助頁只寫「要補齊聲明書」，聲明書套表卻只能從「全部訂單 › 套表列印」找訂單再勾。
現在勾「新舊車主不同人」後，舊車主欄位下方直接有「列印新舊車主不同人聲明書」；
開的是套表列印同一份 PDF，帶入已儲存的資料。上傳仍選填。
"""
from django.urls import reverse

from sales.models import SalesOrder
from sales.services import form_print
from sales.tests.test_subsidy_layout_t85_88 import SubsidyPageHelpers


class OwnerDeclarationPrintTests(SubsidyPageHelpers):
    def trade_in_order(self, *, different):
        self.login_admin()
        order, _vehicle = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(
            is_trade_in_subsidy=True, old_owner_same_as_owner=not different, old_owner_name="潘舊主" if different else "")
        order.refresh_from_db()
        return order

    def print_blocks(self, html):
        return [chunk.split("</div>", 1)[0] for chunk in html.split('<div class="owner-declaration-print')[1:]]

    def test_different_owner_shows_print_button_under_owner_fields(self):
        order = self.trade_in_order(different=True)
        html = self.page(order)
        url = reverse("order_owner_declaration_pdf", args=[order.pk])
        card = html.split("tradein-card__people", 1)[1].split("tradein-card__scrap", 1)[0]
        self.assertIn(f'href="{url}" target="_blank"', card)
        block = self.print_blocks(card)[0]
        self.assertIn("data-old-owner-field", block)
        self.assertNotIn(" hidden", block.split(">", 1)[0])
        self.assertIn("列印新舊車主不同人聲明書", block)
        self.assertIn("到下方「補助文件」上傳", block)
        # 整頁只有這一個入口（order_detail.html 只加一行 include）。
        self.assertEqual(html.count("data-declaration-print"), 1)

    def test_same_owner_keeps_button_hidden_until_ticked(self):
        order = self.trade_in_order(different=False)
        html = self.page(order)
        block = self.print_blocks(html.split("tradein-card__people", 1)[1])[0]
        self.assertIn("data-old-owner-field hidden", block)

    def test_no_trade_in_no_button(self):
        self.login_admin()
        order, _vehicle = self.make_order()
        self.assertNotIn("data-declaration-print", self.page(order))

    def test_pdf_is_the_form_print_declaration(self):
        order = self.trade_in_order(different=True)
        response = self.client.get(reverse("order_owner_declaration_pdf", args=[order.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("inline", response["Content-Disposition"])
        self.assertTrue(b"".join(response.streaming_content).startswith(b"%PDF"))
        self.assertEqual(form_print.FORM_BY_KEY["tax_declaration"].label, "新舊車主不同人聲明書（減徵貨物稅）")

    def test_help_text_says_where_to_supply(self):
        order = self.trade_in_order(different=True)
        html = self.page(order)
        self.assertIn("到下方「補助文件」上傳，聲明書可按「列印新舊車主不同人聲明書」印出", html)
