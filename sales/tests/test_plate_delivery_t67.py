"""1022 投影片（使用者 2026-10-22）：T-67 指定號碼單行以「、」顯示、交車方式與送達地點同一列；T-68 交車表單拿掉提示框與收款證明。"""
from django.test import TestCase
from django.urls import reverse

from sales.forms import OrderEditForm
from sales.models import PaymentRecord, SalesOrder
from sales.tests import test_order_steps as steps


class PlateNumbersTests(TestCase):
    setUp = steps.OrderStepTests.setUp
    make_order = steps.OrderStepTests.make_order
    registered_v2 = steps.OrderStepTests.registered_v2

    def test_split_accepts_common_separators(self):
        self.assertEqual(SalesOrder.split_watched_numbers("8899\n9988、9898，9989, ABC-1234；1111 2222"),
                         ["8899", "9988", "9898", "9989", "ABC-1234", "1111", "2222"])
        self.assertEqual(SalesOrder.split_watched_numbers(""), [])

    def test_form_shows_one_line_and_keeps_stored_text_when_unchanged(self):
        order, _vehicle = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(plate_choice="watch", watched_numbers="8899\n9988\n9898\n9989")
        order.refresh_from_db()
        form = OrderEditForm(instance=order)
        self.assertEqual(form["watched_numbers"].value(), "8899、9988、9898、9989")
        self.assertIn('type="text" name="watched_numbers"', str(form["watched_numbers"]))
        self.assertEqual(order.watched_numbers_display, "8899、9988、9898、9989")
        bound = OrderEditForm(instance=order, data={"watched_numbers": "8899、9988、9898、9989"})
        bound.is_valid()
        self.assertEqual(bound.cleaned_data["watched_numbers"], "8899\n9988\n9898\n9989")

    def test_edited_numbers_are_stored_one_per_line(self):
        order, _vehicle = self.make_order()
        form = OrderEditForm(instance=order, data={"watched_numbers": " 8899，9988 、9898\n9989 "})
        form.is_valid()
        self.assertEqual(form.cleaned_data["watched_numbers"], "8899\n9988\n9898\n9989")

    def test_page_lays_out_numbers_first_row_and_method_with_destination(self):
        order, _vehicle = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(plate_choice="watch", watched_numbers="8899\n9988")
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        section = page.split('id="delivery"', 1)[1].split("</details>", 1)[0]
        self.assertIn('value="8899、9988"', section)
        self.assertRegex(section, r'<input type="text" name="watched_numbers"')
        css = open("static/css/app.css", encoding="utf-8").read()
        self.assertIn(".delivery-layout__numbers { flex: 1 1 calc(100% - 22rem - 3 * var(--space-4)); min-width: 12rem; }", css)
        # 訂單頁其他顯示也用「、」。
        self.assertIn("8899、9988", page)

    def test_contract_print_lists_numbers_with_dunhao(self):
        order, _vehicle = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(plate_choice="watch", watched_numbers="8899\n9988")
        order.refresh_from_db()
        self.assertEqual(order.watched_numbers_display, "8899、9988")
        source = open("templates/sales/contract_print.html", encoding="utf-8").read()
        self.assertIn("order.watched_numbers_display", source)
        pdf_source = open("sales/services/order_contract_pdf.py", encoding="utf-8").read()
        self.assertIn("order.watched_numbers_display or order.plate_preference_note", pdf_source)


class DeliveryBalanceTrimTests(TestCase):
    setUp = steps.OrderStepTests.setUp
    make_order = steps.OrderStepTests.make_order
    registered_v2 = steps.OrderStepTests.registered_v2

    def test_no_hint_box_when_collecting_balance_and_no_proof_field(self):
        order, _vehicle = self.registered_v2()
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        delivery = page.split('id="panel-delivery"', 1)[1].split('id="panel-subsidy"', 1)[0]
        self.assertIn('id="delivery-balance"', delivery)
        self.assertNotIn('id="delivery-payment"', delivery)
        self.assertNotIn("尾款在下方與交車一起登記", delivery)
        fieldset = delivery.split('id="delivery-balance"', 1)[1].split("</fieldset>", 1)[0]
        self.assertNotIn("balance-proof", fieldset)
        self.assertNotIn("收款證明", fieldset)

    def test_no_hint_box_when_balance_settled(self):
        # 尾款收清後也不再放「尾款已收清或由車行掛帳／前往收入與支出」的導向框（T-102）。
        order, _vehicle = self.registered_v2()
        balance = PaymentRecord.objects.get(order=order, system_key="balance")
        PaymentRecord.objects.filter(pk=balance.pk).update(received_amount=balance.expected_amount, confirmed=True)
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        delivery = page.split('id="panel-delivery"', 1)[1].split('id="panel-subsidy"', 1)[0]
        self.assertNotIn('id="delivery-payment"', delivery)
        self.assertNotIn("尾款已收清或由車行掛帳", delivery)
        self.assertNotIn("前往收入與支出", delivery)
