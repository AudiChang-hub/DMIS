"""T-125（使用者 2026-11-06）：問題 1 選 B——沒有訂金就不建訂金列、系統列可改項目名稱、清理既有空訂金列；
問題 2 選 A——車行單的客戶收款顯示「車行收款」，資料值與計算不變。"""
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from sales.forms import PaymentRecordForm
from sales.models import OrderChange, PaymentRecord, SalesOrder
from sales.services.operations_sync import sync_order_operations
from sales.services.payment_summary import payment_summary
from sales.tests import test_order_lifecycle as lifecycle

WORKSPACE = {"HTTP_X_ORDER_WORKSPACE": "1", "HTTP_ACCEPT": "application/json"}


class DepositRowTests(TestCase):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def keys(self, order):
        return sorted(order.payment_records.values_list("system_key", flat=True))

    def save_deposit(self, order, amount, confirmed=False):
        self.client.force_login(self.user)
        data = {"deposit-amount": amount, "deposit-received_on": "2026-11-06", "deposit-method": "cash", "deposit-note": ""}
        if confirmed:
            data["deposit-confirmed"] = "on"
        return self.client.post(reverse("deposit_payment_update", args=[order.pk]), data, **WORKSPACE)

    def test_order_without_deposit_has_no_deposit_row_and_same_summary(self):
        order, _vehicle = self.make_order(deposit=Decimal("0"))
        self.assertNotIn("deposit", self.keys(order))
        self.assertIn("balance", self.keys(order))
        summary = payment_summary(order)
        balance = order.payment_records.get(system_key="balance").expected_amount
        self.assertEqual(summary["customer_expected"], balance)

    def test_deposit_step_creates_row_only_when_amount_is_entered(self):
        order, _vehicle = self.make_order(deposit=Decimal("0"))
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "deposit"}).content.decode()
        self.assertIn("data-deposit-step", page)
        self.assertEqual(self.save_deposit(order, "").status_code, 200)
        self.assertNotIn("deposit", self.keys(order))
        response = self.save_deposit(order, "3000", confirmed=True)
        self.assertEqual(response.status_code, 200, response.content)
        row = order.payment_records.get(system_key="deposit")
        self.assertEqual((row.expected_amount, row.received_amount, row.confirmed), (3000, 3000, True))
        self.assertEqual(SalesOrder.objects.get(pk=order.pk).deposit_amount, 3000)

    def test_existing_empty_deposit_row_is_kept_by_sync(self):
        order, _vehicle = self.make_order(deposit=Decimal("0"))
        PaymentRecord.objects.create(order=order, system_key="deposit", item_name="訂金")
        sync_order_operations(order.pk, update_receivables=True)
        self.assertIn("deposit", self.keys(order))

    def test_renamed_system_row_keeps_its_name(self):
        order, _vehicle = self.make_order(deposit=Decimal("5000"))
        row = order.payment_records.get(system_key="deposit")
        form = PaymentRecordForm(instance=row)
        self.assertFalse(form.fields["item_name"].disabled)
        self.assertTrue(form.fields["receipt_kind"].disabled)
        data = {name: form.initial.get(name) or "" for name in form.fields}
        data.update(item_name="第一筆款", receipt_kind="customer", received_amount="0", expected_amount="5000")
        form = PaymentRecordForm(data, instance=row)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        row.refresh_from_db()
        self.assertTrue(row.item_name_overridden)
        sync_order_operations(order.pk, update_receivables=True)
        row.refresh_from_db()
        self.assertEqual(row.item_name, "第一筆款")


class DealerReceiptLabelTests(TestCase):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def test_dealer_order_shows_dealer_receipt(self):
        dealer, _vehicle = self.make_order(dealer=True, deposit=Decimal("0"))
        row = PaymentRecord.objects.create(order=dealer, item_name="車行付款", received_amount=1000)
        self.assertEqual(row.receipt_kind, "customer")
        self.assertEqual(row.receipt_kind_label, "車行收款")
        self.assertIn(("customer", "車行收款"), PaymentRecordForm(instance=row).fields["receipt_kind"].choices)
        store, _vehicle = self.make_order(deposit=Decimal("0"))
        other = PaymentRecord.objects.create(order=store, item_name="客人付款", received_amount=1000)
        self.assertEqual(other.receipt_kind_label, "客戶收款")
        self.assertIn(("customer", "客戶收款"), PaymentRecordForm(instance=other).fields["receipt_kind"].choices)


class ClearEmptyDepositRowsTests(TestCase):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def run_command(self, *args):
        out = StringIO()
        call_command("clear_empty_deposit_rows", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_then_apply_only_deletes_empty_rows(self):
        empty_order, _vehicle = self.make_order(deposit=Decimal("0"))
        empty = PaymentRecord.objects.create(order=empty_order, system_key="deposit", item_name="訂金")
        noted_order, _vehicle = self.make_order(deposit=Decimal("0"))
        noted = PaymentRecord.objects.create(order=noted_order, system_key="deposit", item_name="訂金", note="客人說下週付")
        paid_order, _vehicle = self.make_order(deposit=Decimal("5000"))
        paid = paid_order.payment_records.get(system_key="deposit")
        before = payment_summary(SalesOrder.objects.get(pk=empty_order.pk))

        output = self.run_command()
        self.assertIn("符合條件的空訂金列：1 筆", output)
        self.assertIn("略過（有帳戶、證明或備註）：1", output)
        self.assertTrue(PaymentRecord.objects.filter(pk=empty.pk).exists())

        output = self.run_command("--apply")
        self.assertIn("完成：刪除 1 筆", output)
        self.assertFalse(PaymentRecord.objects.filter(pk=empty.pk).exists())
        self.assertTrue(PaymentRecord.objects.filter(pk__in=[noted.pk, paid.pk]).count() == 2)
        change = OrderChange.objects.get(order=empty_order, actor_name__startswith="系統資料整理（clear_empty_deposit_rows）")
        self.assertIn(f"刪除收款列 #{empty.pk}：訂金", change.changes)
        after = payment_summary(SalesOrder.objects.get(pk=empty_order.pk))
        self.assertEqual(before["customer_expected"], after["customer_expected"])
        self.assertEqual(before["settled"], after["settled"])

    def test_new_row_template_on_dealer_order_shows_dealer_receipt(self):
        from sales.forms import PaymentRecordFormSet
        dealer, _vehicle = self.make_order(dealer=True, deposit=Decimal("0"))
        formset = PaymentRecordFormSet(instance=dealer, prefix="payments")
        self.assertIn(("customer", "車行收款"), formset.empty_form.fields["receipt_kind"].choices)
