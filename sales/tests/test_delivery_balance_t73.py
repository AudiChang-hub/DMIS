"""1022 投影片二（使用者 2026-10-22）：T-73 尾款移到交車最上方並列出應收計算式；T-75 實收不得少於應收；T-72 提示框不誤寫已收清。"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from sales.forms import DeliveryPaymentForm
from sales.models import PaymentRecord, SalesOrder
from sales.services.payment_summary import balance_breakdown, payment_summary
from sales.tests import test_order_lifecycle as lifecycle
from sales.tests import test_order_steps as steps


def delivery_panel(page):
    return page.split('id="panel-delivery"', 1)[1].split('id="panel-subsidy"', 1)[0]


class DeliveryBalanceTests(TestCase):
    setUp = steps.OrderStepTests.setUp
    make_order = steps.OrderStepTests.make_order
    registered_v2 = steps.OrderStepTests.registered_v2
    delivery_payload = lifecycle.OrderLifecycleTests.delivery_payload

    def test_breakdown_matches_delivery_due(self):
        order, _vehicle = self.registered_v2(deposit=Decimal("5000"))
        PaymentRecord.objects.filter(order=order, system_key="deposit").update(received_amount=Decimal("5000"), confirmed=True)
        order = SalesOrder.objects.get(pk=order.pk)
        summary = payment_summary(order)
        breakdown = balance_breakdown(order, summary)
        self.assertTrue(breakdown["exact"])
        self.assertEqual(breakdown["due"], summary["delivery_due"])
        signed = sum((amount if sign == "+" else -amount for _label, amount, sign in breakdown["lines"]), Decimal("0"))
        self.assertEqual(signed, summary["delivery_due"])
        labels = [label for label, _amount, _sign in breakdown["lines"]]
        # 從組成項目開始（使用者 2026-10-22 T-76）：車價在最前，總價＝各項加總－優惠。
        self.assertEqual(labels[0], "車價")
        self.assertIn("已收訂金", labels)
        self.assertEqual(sum((row["amount"] for row in breakdown["charges"]), Decimal("0")) - breakdown["discount"], breakdown["total"])
        self.assertEqual(breakdown["total"], order.discounted_total)

    def test_balance_block_is_first_in_delivery_step_with_formula(self):
        order, _vehicle = self.registered_v2()
        self.client.force_login(self.user)
        delivery = delivery_panel(self.client.get(reverse("order_detail", args=[order.pk])).content.decode())
        body = delivery.split('<div class="order-step__body">', 1)[1]
        self.assertTrue(body.lstrip().startswith('<fieldset class="delivery-balance" id="delivery-balance"'))
        self.assertLess(delivery.index('id="delivery-balance"'), delivery.index('id="delivery-completion-form"'))
        self.assertIn('class="balance-ledger"', delivery)
        self.assertIn('<div class="ledger__row is-due"><dt>應收</dt>', delivery)
        self.assertIn("data-balance-summary", delivery)
        self.assertRegex(delivery, r'name="balance-received_amount"[^>]*form="delivery-completion-form"')
        self.assertNotIn('id="delivery-payment"', delivery)
        self.assertNotIn("balance-proof", delivery)

    def test_received_must_cover_due(self):
        order, _vehicle = self.registered_v2()
        balance = PaymentRecord.objects.get(order=order, system_key="balance")
        due = payment_summary(order)["delivery_due"]
        short = DeliveryPaymentForm(data={"received_amount": str(due - 1), "received_on": "2026-10-22", "payment_method": "現金",
                                          "confirmed": "on"}, instance=balance, due=due)
        self.assertFalse(short.is_valid())
        self.assertIn("不得少於應收", short.errors["received_amount"][0])
        balance = PaymentRecord.objects.get(pk=balance.pk)
        enough = DeliveryPaymentForm(data={"received_amount": str(due), "received_on": "2026-10-22", "payment_method": "現金",
                                           "confirmed": "on"}, instance=balance, due=due)
        self.assertTrue(enough.is_valid(), enough.errors)
        zero = DeliveryPaymentForm(data={"received_amount": "", "received_on": "", "payment_method": ""},
                                   instance=PaymentRecord.objects.get(pk=balance.pk), due=Decimal("0"))
        self.assertFalse(zero.fields["received_amount"].required)
        self.assertTrue(zero.is_valid(), zero.errors)

    def test_delivery_endpoint_requires_amount_when_due(self):
        order, _vehicle = self.registered_v2()
        self.client.force_login(self.user)
        response = self.client.post(reverse("delivery_complete", args=[order.pk]), self.delivery_payload(), follow=True)
        self.assertContains(response, "請填寫實收金額")
        due = payment_summary(order)["delivery_due"]
        response = self.client.post(reverse("delivery_complete", args=[order.pk]), {
            **self.delivery_payload(), "balance-received_amount": str(due - 1), "balance-received_on": "2026-10-22",
            "balance-payment_method": "現金"}, follow=True)
        self.assertContains(response, "不得少於應收")
        order.refresh_from_db()
        self.assertFalse(order.is_delivered)
        response = self.client.post(reverse("delivery_complete", args=[order.pk]), {
            **self.delivery_payload(), "balance-received_amount": str(due), "balance-received_on": "2026-10-22",
            "balance-payment_method": "現金"}, follow=True)
        order.refresh_from_db()
        self.assertTrue(order.is_delivered)

    def test_scripts_gate_button_on_received_amount(self):
        script = open("static/js/delivery-form.js", encoding="utf-8").read()
        self.assertIn('const short = due > 0 && !(Number(amount.value || 0) >= due);', script)
        workspace = open("static/js/order-workspace.js", encoding="utf-8").read()
        self.assertIn("button.disabled = !ready || button.dataset.balanceShort === '1';", workspace)

    def test_hint_box_does_not_claim_settled_when_balance_open_without_permission(self):
        from unittest import mock
        order, _vehicle = self.registered_v2()
        self.client.force_login(self.user)
        with mock.patch("sales.services.order_workspace.can_edit_finance", return_value=False):
            delivery = delivery_panel(self.client.get(reverse("order_detail", args=[order.pk])).content.decode())
        self.assertNotIn("尾款已收清或由車行掛帳", delivery)
        self.assertIn("尾款尚未收清", delivery)


class BalanceStatementTests(TestCase):
    """T-76：應收對帳單從組成項目加到總價、再扣到應收；0 元不列；對不上時改列收支合計並標示。"""
    setUp = steps.OrderStepTests.setUp
    make_order = steps.OrderStepTests.make_order
    registered_v2 = steps.OrderStepTests.registered_v2

    def order_with_parts(self):
        from sales.models import AccessoryLine, OtherFeeLine
        order, _vehicle = self.registered_v2(deposit=Decimal("4800"))
        AccessoryLine.objects.create(order=order, name="後保桿", quantity=1, amount=Decimal("2500"))
        AccessoryLine.objects.create(order=order, name="兒童座椅", quantity=2, amount=Decimal("1500"))
        AccessoryLine.objects.create(order=order, name="後背包", quantity=1, amount=Decimal("0"), line_type="gift")
        OtherFeeLine.objects.create(order=order, name="代辦費", amount=Decimal("600"))
        SalesOrder.objects.filter(pk=order.pk).update(plate_selection_fee=Decimal("1200"), approved_discount_amount=Decimal("1000"),
                                                      discount_status="approved")
        order = SalesOrder.objects.get(pk=order.pk)
        balance = order.calculate_balance()
        SalesOrder.objects.filter(pk=order.pk).update(actual_balance=balance, calculated_balance=balance)
        PaymentRecord.objects.filter(order=order, system_key="deposit").update(expected_amount=Decimal("4800"), received_amount=Decimal("4800"), confirmed=True)
        from sales.services.operations_sync import sync_order_operations
        sync_order_operations(order.pk)
        return SalesOrder.objects.get(pk=order.pk)

    def test_components_add_up_to_total_and_due(self):
        order = self.order_with_parts()
        b = balance_breakdown(order)
        self.assertTrue(b["exact"], b)
        labels = [row["label"] for row in b["charges"]]
        self.assertEqual(labels[:2], ["車價", "配件"])
        self.assertIn("選號費", labels)
        self.assertIn("其他費用", labels)
        self.assertNotIn("分期開辦費", labels)  # 0 元不列
        accessories = next(row for row in b["charges"] if row["label"] == "配件")
        self.assertEqual(accessories["amount"], Decimal("5500"))
        self.assertEqual([name for name, _amount in accessories["items"]], ["後保桿", "兒童座椅 ×2"])  # 贈品 0 元不列
        self.assertEqual(b["discount"], Decimal("1000"))
        self.assertEqual(b["total"], order.discounted_total)
        self.assertEqual(b["total"] - Decimal("4800"), b["due"])
        self.assertEqual(b["due"], payment_summary(order)["delivery_due"])

    def test_page_lists_components_subtotals_and_due(self):
        order = self.order_with_parts()
        self.client.force_login(self.user)
        delivery = delivery_panel(self.client.get(reverse("order_detail", args=[order.pk])).content.decode())
        ledger = delivery.split('class="balance-ledger"', 1)[1].split("</section>", 1)[0]
        order_of = [ledger.index(text) for text in ("<dt>車價", "<dt>配件", "後保桿", "兒童座椅 ×2", "<dt>選號費", "<dt>其他費用",
                                                    "<dt>費用合計", "<dt>已核准優惠", "<dt>總價", "<dt>已收訂金", "<dt>應收")]
        self.assertEqual(order_of, sorted(order_of))
        self.assertNotIn("後背包", ledger)
        self.assertNotIn("ledger__note", ledger)

    def test_mismatch_falls_back_to_ledger_totals_with_note(self):
        order = self.order_with_parts()
        balance = PaymentRecord.objects.get(order=order, system_key="balance")
        PaymentRecord.objects.filter(pk=balance.pk).update(expected_amount=balance.expected_amount + 777, expected_amount_overridden=True)
        order = SalesOrder.objects.get(pk=order.pk)
        b = balance_breakdown(order)
        self.assertFalse(b["exact"])
        self.assertEqual(b["due"], payment_summary(order)["delivery_due"])
        self.assertEqual([row["label"] for row in b["fallback"]], ["客戶應收合計", "已收款"])
        self.client.force_login(self.user)
        delivery = delivery_panel(self.client.get(reverse("order_detail", args=[order.pk])).content.decode())
        self.assertIn("逐項加總對不上", delivery)
        self.assertIn("<dt>客戶應收合計</dt>", delivery)
