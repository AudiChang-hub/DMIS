"""1.86.30（使用者 2026-10-20 T-29 方案 A）：訂金只有一個數字，「已收妥」開關自動儲存。

建單填了訂金就已收妥（見 test_intake_deposit_discount）；訂單頁的訂金步驟只留金額、日期、方式、備註與開關，
未收妥改金額同步訂單訂金、收妥後鎖定，取消訂單的應退依已收妥的訂金計算。
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.forms import OrderEditForm
from sales.models import OrderChange, OrderEvent, PaymentRecord, SalesOrder
from sales.services.order_steps import build_order_steps
from sales.services.payment_ledger import complete_cancellation_refund, reverse_payment
from sales.tests import test_order_lifecycle as lifecycle

WORKSPACE = {"HTTP_X_ORDER_WORKSPACE": "1", "HTTP_ACCEPT": "application/json"}


class DepositStepTests(TestCase):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def order(self, deposit=Decimal("5000")):
        order, _vehicle = self.make_order(deposit=deposit)
        SalesOrder.objects.filter(pk=order.pk).update(cash_receivable_v2=True)
        PaymentRecord.objects.filter(order=order, system_key="deposit").update(received_amount=0)
        self.client.force_login(self.user)
        return SalesOrder.objects.get(pk=order.pk)

    def save(self, order, **values):
        data = {"deposit-amount": "5000", "deposit-received_on": "2026-10-20", "deposit-method": "cash", "deposit-note": ""}
        data.update({f"deposit-{key}": value for key, value in values.items()})
        data = {key: value for key, value in data.items() if value is not None}
        return self.client.post(reverse("deposit_payment_update", args=[order.pk]), data, **WORKSPACE)

    def deposit(self, order):
        return PaymentRecord.objects.get(order=order, system_key="deposit")

    def test_step_shows_one_amount_and_a_received_switch_only(self):
        order = self.order()
        page = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "deposit"}).content.decode()
        panel = page.split('id="deposit-payment"', 1)[1].split("</form>", 1)[0]
        self.assertIn('data-workspace-save="deposit"', page)
        self.assertIn('name="deposit-confirmed"', panel)
        self.assertIn('role="switch"', panel)
        self.assertIn("訂金待收妥", panel)
        for name in ("deposit-amount", "deposit-received_on", "deposit-method", "deposit-note"):
            self.assertIn(f'name="{name}"', panel)
        for gone in ("約定訂金", "receiving_account", "收款帳戶", "proof", "收款證明", "duplicate_confirmed", "確認非重複收款", "登記訂金收款", 'type="submit"'):
            self.assertNotIn(gone, panel)
        self.assertEqual(build_order_steps(order)["steps"]["deposit"]["summary"], "待收妥 5,000")

    def test_switch_on_posts_to_ledger_and_switch_off_reverts_to_pending(self):
        order = self.order()
        response = self.save(order, confirmed="on")
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual((payload["deposit"]["confirmed"], payload["deposit"]["locked"], payload["deposit"]["step_state"]), (True, True, "done"))
        self.assertEqual(payload["deposit"]["summary"], "已收妥 5,000")
        deposit = self.deposit(order)
        self.assertEqual((deposit.received_amount, deposit.confirmed, deposit.payment_method, deposit.received_on),
                         (Decimal("5000"), True, "現金", date(2026, 10, 20)))
        self.assertTrue(deposit.confirmed_by)
        self.assertTrue(OrderEvent.objects.filter(order=order, description="訂金 $5,000 已收妥並入帳").exists())

        response = self.save(order, confirmed=None)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["deposit"]["confirmed"], False)
        deposit = self.deposit(order)
        self.assertEqual((deposit.received_amount, deposit.confirmed, deposit.confirmed_by, deposit.confirmed_at),
                         (Decimal("0"), False, "", None))
        self.assertEqual(deposit.expected_amount, Decimal("5000"))
        self.assertTrue(OrderEvent.objects.filter(order=order, description__startswith="取消訂金已收妥").exists())

    def test_editing_amount_while_pending_syncs_the_order_deposit(self):
        order = self.order()
        before = order.calculate_balance()
        response = self.save(order, amount="8000", method="transfer", note="客人改付")
        self.assertTrue(response.json()["ok"])
        order.refresh_from_db()
        self.assertEqual((order.deposit_amount, order.deposit_method, order.deposit_date), (Decimal("8000"), "transfer", date(2026, 10, 20)))
        self.assertEqual(order.calculated_balance, before - 3000)
        deposit = self.deposit(order)
        self.assertEqual((deposit.expected_amount, deposit.received_amount, deposit.confirmed, deposit.note),
                         (Decimal("8000"), Decimal("0"), False, "客人改付"))
        change = OrderChange.objects.filter(order=order, reason="訂金步驟").latest("pk")
        self.assertEqual(change.changes["deposit_amount"], {"before": "5000", "after": "8000"})
        # 訂單表單不再帶訂金欄位（使用者 2026-10-21 T-44），同步內容也不含訂金，不會蓋回舊值。
        self.assertNotIn("deposit_amount", response.json()["sync"]["order"])

    def test_received_deposit_is_locked_until_switched_off(self):
        order = self.order()
        self.save(order, confirmed="on")
        # 收妥後偷送新金額：伺服器照鎖定值，不改帳本也不改訂單。
        response = self.save(order, amount="9999", received_on="2026-10-01", method="card", confirmed="on", note="補備註")
        self.assertTrue(response.json()["ok"])
        deposit = self.deposit(order)
        order.refresh_from_db()
        self.assertEqual((deposit.received_amount, deposit.payment_method, deposit.note), (Decimal("5000"), "現金", "補備註"))
        self.assertEqual(order.deposit_amount, Decimal("5000"))
        page = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "deposit"}).content.decode()
        panel = page.split('id="deposit-payment"', 1)[1].split("</form>", 1)[0]
        self.assertIn("訂金已收妥", panel)
        self.assertRegex(panel, r'name="deposit-amount"[^>]*disabled')
        # 訂金只在「訂金與費用」步驟修改（使用者 2026-10-21 T-44）：訂單表單沒有訂金欄位。
        for name in ("deposit_amount", "deposit_date", "deposit_method"):
            self.assertNotIn(name, OrderEditForm(instance=order).fields)
        # 關掉後解鎖，可以改金額。
        self.save(order, confirmed=None)
        self.save(order, amount="6000")
        order.refresh_from_db()
        self.assertEqual(order.deposit_amount, Decimal("6000"))

    def test_switch_on_needs_amount_and_method(self):
        order = self.order()
        response = self.save(order, amount="", confirmed="on")
        self.assertEqual(response.status_code, 400)
        self.assertIn("deposit-amount", response.json()["errors"])
        response = self.save(order, method="", confirmed="on")
        self.assertIn("deposit-method", response.json()["errors"])
        self.assertFalse(self.deposit(order).confirmed)

    def test_same_day_same_amount_is_not_blocked_on_the_deposit_step(self):
        order = self.order()
        PaymentRecord.objects.create(order=order, item_name="人工收款", receipt_kind="customer", expected_amount=0,
                                     received_amount=5000, received_on=date(2026, 10, 20), payment_method="現金",
                                     confirmed=True, confirmed_by="tester", confirmed_at=timezone.now())
        response = self.save(order, confirmed="on")
        self.assertTrue(response.json()["ok"], response.content)
        self.assertTrue(self.deposit(order).confirmed)

    def test_reversed_deposit_cannot_be_switched_off(self):
        order = self.order()
        self.save(order, confirmed="on")
        reverse_payment(order_id=order.pk, payment_id=self.deposit(order).pk, actor_name="tester", reason="登記錯誤")
        # 已沖銷的訂金開關停用：送出的取消勾選不採用，仍維持已收妥（帳本規則，2026-10-17）。
        page = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "deposit"}).content.decode()
        self.assertRegex(page.split('id="deposit-payment"', 1)[1], r'name="deposit-confirmed"[^>]*disabled')
        response = self.save(order, confirmed=None)
        self.assertTrue(response.json()["ok"])
        self.assertTrue(self.deposit(order).confirmed)

    def test_cancellation_refunds_the_received_deposit(self):
        order = self.order()
        self.save(order, confirmed="on")
        SalesOrder.objects.filter(pk=order.pk).update(status=SalesOrder.Status.CANCEL_REFUND_PENDING)
        order.refresh_from_db()
        settled = complete_cancellation_refund(order, actor_name="tester", forfeited_amount=1000,
                                               completed_on=date(2026, 10, 21), method="cash", forfeit_reason="客人取消")
        self.assertEqual((settled.refund_amount, settled.forfeited_amount, settled.status),
                         (Decimal("4000"), Decimal("1000"), SalesOrder.Status.CANCELLED))

    def test_pending_deposit_is_not_refundable_on_cancellation(self):
        order = self.order()
        SalesOrder.objects.filter(pk=order.pk).update(status=SalesOrder.Status.CANCEL_REFUND_PENDING)
        order.refresh_from_db()
        settled = complete_cancellation_refund(order, actor_name="tester", forfeited_amount=0,
                                               completed_on=date(2026, 10, 21), method="cash")
        self.assertEqual(settled.refund_amount, Decimal("0"))
