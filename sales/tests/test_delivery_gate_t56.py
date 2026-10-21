"""T-56（使用者 2026-10-21）：自動儲存後交車按鈕與原因清單沿用頁面判斷；系統尾款列標出應收尾款。"""
import re
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from sales.models import PaymentRecord, SalesOrder
from sales.tests import test_order_steps as steps


def delivery_panel(page):
    return page.split('id="panel-delivery"', 1)[1].split('id="panel-subsidy"', 1)[0]


class DeliveryGateTests(TestCase):
    setUp = steps.OrderStepTests.setUp
    make_order = steps.OrderStepTests.make_order
    registered_v2 = steps.OrderStepTests.registered_v2
    section_payload = steps.OrderStepTests.section_payload

    def autosave(self, order, **values):
        response = self.client.post(reverse("order_operations", args=[order.pk]),
                                    self.section_payload(order, "fulfillment", **values), HTTP_X_ORDER_WORKSPACE="1")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_autosave_keeps_delivery_ready_when_balance_is_collected_in_delivery_form(self):
        order, _vehicle = self.registered_v2()
        self.client.force_login(self.user)
        delivery = delivery_panel(self.client.get(reverse("order_detail", args=[order.pk])).content.decode())
        self.assertIn('id="delivery-balance"', delivery)
        self.assertRegex(delivery, r'<ul class="delivery-blockers" data-delivery-blockers[^>]* hidden>')
        self.assertNotRegex(delivery, r'<button class="button primary" type="submit" disabled')
        payload = self.autosave(order, helmet="安全帽一頂")
        # 與頁面同一判斷：尾款在交車表單一併登記，不擋按鈕。
        self.assertTrue(payload["delivery_ready"])
        self.assertTrue(payload["delivery_collect_balance"])
        self.assertEqual(payload["delivery_blockers"], [])
        # 頁面若沒有尾款欄位，畫面改用含尾款的判斷。
        self.assertTrue(any("尾款尚未收清" in item for item in payload["delivery_blockers_strict"]))

    def test_autosave_reports_every_blocker_for_the_list_under_the_button(self):
        order, _vehicle = self.registered_v2()
        SalesOrder.objects.filter(pk=order.pk).update(discount_status=SalesOrder.DiscountStatus.PENDING)
        order.refresh_from_db()
        self.client.force_login(self.user)
        delivery = delivery_panel(self.client.get(reverse("order_detail", args=[order.pk])).content.decode())
        listed = re.search(r'<ul class="delivery-blockers" data-delivery-blockers[^>]*>(.*?)</ul>', delivery, re.S)
        self.assertNotIn(" hidden", listed.group(0).split(">", 1)[0])
        self.assertIn("折扣申請尚待確認，確認或退回後才能交車。", listed.group(1))
        self.assertRegex(delivery, r'<button class="button primary" type="submit" disabled')
        payload = self.autosave(order, helmet="安全帽一頂")
        self.assertFalse(payload["delivery_ready"])
        self.assertIn("折扣申請尚待確認，確認或退回後才能交車。", payload["delivery_blockers"])
        self.assertEqual(payload["delivery_blocker"], payload["delivery_blockers"][0])

    def test_settled_balance_needs_no_collection(self):
        order, _vehicle = self.registered_v2()
        balance = PaymentRecord.objects.get(order=order, system_key="balance")
        PaymentRecord.objects.filter(pk=balance.pk).update(received_amount=balance.expected_amount, confirmed=True)
        self.client.force_login(self.user)
        payload = self.autosave(SalesOrder.objects.get(pk=order.pk), helmet="安全帽一頂")
        self.assertFalse(payload["delivery_collect_balance"])
        self.assertTrue(payload["delivery_ready"])
        self.assertEqual(payload["delivery_blockers_strict"], [])

    def test_workspace_script_updates_button_and_blocker_list(self):
        script = (Path(settings.BASE_DIR) / "static/js/order-workspace.js").read_text(encoding="utf-8")
        self.assertIn("payload.delivery_collect_balance && !canCollect ? payload.delivery_blockers_strict : payload.delivery_blockers", script)
        self.assertIn("root.querySelectorAll('[data-delivery-blockers]')", script)
        self.assertIn("list.hidden = ready;", script)
        # 按鈕文字與頁面一致：在交車表單收尾款時是「收尾款並完成交車」。
        self.assertIn("canCollect && payload.delivery_collect_balance ? '收尾款並完成交車' : '確認完成交付'", script)

    def test_system_balance_row_shows_receivable_as_text_only(self):
        order, _vehicle = self.registered_v2()
        balance = PaymentRecord.objects.get(order=order, system_key="balance")
        self.assertGreater(balance.expected_amount, Decimal("0"))
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        receipts = page.split('id="payment-records"', 1)[1].split('id="payment-empty-row"', 1)[0]
        # 未收的系統尾款列也列在收款明細（原本是隱藏的應收列），標出應收尾款、沒有刪除鈕。
        self.assertEqual(receipts.count("data-balance-due>"), 1)
        row = receipts[receipts.rindex("data-payment-row", 0, receipts.index("data-balance-due>")):]
        row = row[:row.index("receipt-actions") + 200]
        self.assertNotIn("data-delete-payment", row)
        hidden_expectations = page.split('id="payment-empty-row"', 1)[1]
        self.assertNotIn(f'value="{balance.pk}"', "".join(re.findall(r"<div data-payment-expectation>.*?</div>", hidden_expectations, re.S)))
        self.assertIn(f"應收尾款 $<span data-balance-due-amount>{balance.expected_amount:,.0f}</span>，收到尾款填在這一列", receipts)
        # 應收仍不可在畫面上修改（T-46）：只有隱藏欄位，沒有可輸入的應收金額。
        self.assertNotRegex(receipts, r'<input type="(?:number|text)" name="[^"]*-expected_amount"')
        empty_row = page.split('id="payment-empty-row"', 1)[1].split("</template>", 1)[0]
        self.assertNotIn("data-balance-due", empty_row)
