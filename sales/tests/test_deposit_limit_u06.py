"""UAT U-06（使用者 2026-11-03 選方案 A）：訂單頁「訂金」步驟的訂金大於總價時擋下，原因標在金額欄；
分期單訂金只超過分期外應收時只提醒、不擋；牌險留空由系統計算時不寫出總價。"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from sales.models import SalesOrder
from sales.services.deposit_step import deposit_limit_error, deposit_warning
from sales.tests import test_deposit_step_1830 as base

WORKSPACE = base.WORKSPACE


class DepositLimitTests(TestCase):
    setUp = base.DepositStepTests.setUp
    make_order = base.DepositStepTests.make_order
    order = base.DepositStepTests.order
    save = base.DepositStepTests.save

    def test_deposit_over_total_is_blocked_next_to_amount(self):
        order = self.order()
        total = order.discounted_total
        response = self.save(order, amount=str(total + 1))
        self.assertEqual(response.status_code, 400)
        errors = response.json()["errors"]["deposit-amount"]
        self.assertIn("訂金不能大於", errors[0])
        order.refresh_from_db()
        self.assertEqual(order.deposit_amount, Decimal("5000"))
        # 剛好等於總價可以存。
        self.assertTrue(self.save(order, amount=str(total)).json()["ok"])

    def test_auto_plate_insurance_hides_total(self):
        order = self.order()
        SalesOrder.objects.filter(pk=order.pk).update(plate_insurance_auto=True)
        order.refresh_from_db()
        message = deposit_limit_error(order, order.discounted_total + 1)
        self.assertIn("訂金不能大於這張單的總價", message)
        self.assertNotIn(f"{order.discounted_total:,.0f}", message)
        SalesOrder.objects.filter(pk=order.pk).update(plate_insurance_auto=False)
        order.refresh_from_db()
        self.assertIn(f"{order.discounted_total:,.0f}", deposit_limit_error(order, order.discounted_total + 1))

    def test_installment_deposit_over_self_paid_part_only_warns(self):
        from sales.services.customer_receivable import installment_customer_part
        order = self.order()
        SalesOrder.objects.filter(pk=order.pk).update(payment_type=SalesOrder.PaymentType.INSTALLMENT)
        order.refresh_from_db()
        part = installment_customer_part(order)
        amount = part + 1000
        self.assertLessEqual(amount, order.discounted_total)
        self.assertEqual(deposit_limit_error(order, amount), "")
        self.assertIn("提醒：訂金超過分期外應收", deposit_warning(order, amount))
        self.assertEqual(deposit_warning(order, part), "")
        response = self.save(order, amount=str(amount))
        payload = response.json()
        self.assertTrue(payload["ok"], response.content)
        self.assertIn("提醒：訂金超過分期外應收", payload["deposit"]["warning"])
        page = self.client.get(reverse("order_detail", args=[order.pk]) + "?tab=deposit").content.decode()
        self.assertIn("data-deposit-warning", page)
        self.assertIn("提醒：訂金超過分期外應收", page)

    def test_cash_order_has_no_warning(self):
        order = self.order()
        self.assertEqual(deposit_warning(order, order.discounted_total), "")
        self.assertTrue(self.client.post(reverse("deposit_payment_update", args=[order.pk]),
                                         {"deposit-amount": "100", "deposit-method": "cash"}, **WORKSPACE).json()["ok"])
