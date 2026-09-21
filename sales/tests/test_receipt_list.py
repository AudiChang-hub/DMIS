from datetime import date
from decimal import Decimal

from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse

from sales.forms import OrderOperationsForm, PaymentRecordFormSet
from sales.models import PaymentRecord, OrderChange, OrderOperationsProfile
from sales.services.operations_sync import sync_order_operations
from sales.services.payment_summary import payment_summary
from sales.services.sales_metrics import filter_payment_risk
from sales.tests import test_order_workspace as workspace_fixtures
from sales.tests.test_order_workspace import form_data, formset_data


class ReceiptListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        workspace_fixtures.OrderWorkspaceTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.client.force_login(self.admin)

    def receipt(self, amount, **kwargs):
        return PaymentRecord.objects.create(order=self.order, item_name="自行命名", received_amount=amount,
                                            received_on=date(2026, 9, 21), payment_method="匯款", **kwargs)

    def payload(self):
        self.order.refresh_from_db()
        return {**form_data(OrderOperationsForm(instance=OrderOperationsProfile.objects.get(order=self.order), prefix="operations")),
                **formset_data(PaymentRecordFormSet(instance=self.order, prefix="payments"))}

    def test_default_only_deposit_visible_and_expectations_preserved(self):
        response = self.client.get(reverse("order_detail", args=[self.order.pk]))
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.content, "html.parser")
        rows = soup.select("#payment-records [data-payment-row]")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].select_one('[name$="-item_name"]')["value"], "訂金")
        self.assertEqual(len(soup.select("[data-payment-expectation]")), 1)
        self.assertNotContains(response, "訂金、客戶收款與分期撥款")
        self.assertEqual(self.order.payment_records.get(system_key="balance").expected_amount, 70000)

    def test_confirmed_customer_receipts_accumulate_and_reversal_restores_due(self):
        self.receipt(20000, confirmed=True)
        last = self.receipt(50000, confirmed=False)
        self.assertEqual(payment_summary(self.order)["customer_due"], 50000)
        last.confirmed = True
        last.save()
        self.assertTrue(payment_summary(self.order)["settled"])
        self.assertTrue(OrderOperationsProfile.objects.get(order=self.order).payment_confirmed)
        last.confirmed = False
        last.save()
        self.assertFalse(OrderOperationsProfile.objects.get(order=self.order).payment_confirmed)
        self.assertEqual(payment_summary(self.order)["customer_due"], 50000)

    def test_deposit_only_cannot_settle_whole_order(self):
        self.order.deposit_amount = 2000
        self.order.actual_balance = 68000
        self.order.save()
        deposit = self.order.payment_records.get(system_key="deposit")
        deposit.received_amount = 2000
        deposit.confirmed = True
        deposit.save()
        self.assertEqual(payment_summary(self.order)["customer_due"], 68000)
        self.assertFalse(payment_summary(self.order)["settled"])

    def test_lender_money_never_covers_customer_due_or_guesses_item_name(self):
        self.receipt(70000, confirmed=True, receipt_kind="lender")
        self.assertEqual(payment_summary(self.order)["customer_due"], 70000)
        self.assertFalse(payment_summary(self.order)["customer_settled"])
        self.assertEqual(payment_summary(self.order)["lender_received"], 70000)

    def test_split_lender_disbursement_updates_profit_and_reversal(self):
        self.order.payment_type = "installment"
        self.order.installment_amount = 60000
        self.order.actual_balance = 62000
        self.order.balance_adjustment_reason = "測試分期外應收"
        self.order.save()
        first = self.receipt(20000, confirmed=True, receipt_kind="lender")
        second = self.receipt(40000, confirmed=True, receipt_kind="lender")
        self.assertEqual(OrderOperationsProfile.objects.get(order=self.order).actual_disbursement, 60000)
        self.assertEqual(payment_summary(self.order)["customer_due"], 2000)
        second.delete()
        self.assertEqual(OrderOperationsProfile.objects.get(order=self.order).actual_disbursement, 20000)
        first.confirmed = False
        first.save()
        self.assertEqual(OrderOperationsProfile.objects.get(order=self.order).payment_disbursement_snapshot, {})

    def test_old_payment_and_proof_stay_visible(self):
        balance = self.order.payment_records.get(system_key="balance")
        balance.proof = "orders/payments/test-only.pdf"
        balance.expected_amount_overridden = True
        balance.expected_amount_override_reason = "保留原調整"
        balance.expected_amount = 68000
        balance.save()
        sync_order_operations(self.order.pk)
        balance.refresh_from_db()
        self.assertFalse(balance.is_receivable_only)
        self.assertEqual(balance.expected_amount, 68000)
        self.assertEqual(balance.proof.name, "orders/payments/test-only.pdf")

    def test_add_and_edit_again_without_reload_with_audit(self):
        payload = self.payload()
        index = int(payload["payments-TOTAL_FORMS"])
        payload.update({"payments-TOTAL_FORMS": str(index + 1),
                        f"payments-{index}-item_name": "配件收款", f"payments-{index}-receipt_kind": "customer",
                        f"payments-{index}-received_amount": "70000", f"payments-{index}-received_on": "2026-09-21",
                        f"payments-{index}-payment_method": "匯款", f"payments-{index}-confirmed": "on"})
        url = reverse("order_operations", args=[self.order.pk])
        response = self.client.post(url, payload, HTTP_X_ORDER_WORKSPACE="1")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["receipt_summary"]["customer_due"], "0")
        self.assertTrue(response.json()["delivery_ready"])
        row = self.order.payment_records.get(item_name="配件收款")
        self.assertTrue(row.confirmed_by)
        self.assertIsNotNone(row.confirmed_at)
        self.assertEqual(row.expected_amount, 0)
        self.assertIn("receipt_kind", str(OrderChange.objects.filter(order=self.order).last().changes))
        payload = self.payload()
        formset = PaymentRecordFormSet(instance=self.order, prefix="payments")
        row_form = next(f for f in formset if f.instance.pk == row.pk)
        payload[row_form.add_prefix("received_amount")] = "60000"
        payload.pop(row_form.add_prefix("confirmed"))
        response = self.client.post(url, payload, HTTP_X_ORDER_WORKSPACE="1")
        self.assertEqual(response.status_code, 200, response.content)
        row.refresh_from_db()
        self.assertFalse(row.confirmed)
        self.assertIsNone(row.confirmed_at)
        self.assertEqual(row.confirmed_by, "")

    def test_receipt_classification_change_recalculates_both_buckets(self):
        row = self.receipt(70000, confirmed=True)
        row.receipt_kind = "lender"
        row.save()
        self.assertEqual(payment_summary(self.order)["customer_due"], 70000)
        self.assertFalse(OrderOperationsProfile.objects.get(order=self.order).payment_confirmed)

    def test_fully_paid_not_in_outstanding_report(self):
        self.receipt(70000, confirmed=True)
        self.assertFalse(filter_payment_risk(type(self.order).objects.filter(pk=self.order.pk), "outstanding").exists())

    def test_unconfirmed_extra_receipt_remains_in_review_even_when_other_receipts_settled(self):
        self.receipt(70000, confirmed=True)
        self.receipt(1000, confirmed=False)
        self.assertTrue(filter_payment_risk(type(self.order).objects.filter(pk=self.order.pk), "unconfirmed").exists())

    def test_legacy_named_system_receivable_not_dropped(self):
        self.receipt(70000, confirmed=True)
        PaymentRecord.objects.create(order=self.order, system_key="legacy_extra", item_name="歷史額外應收", expected_amount=1500)
        self.assertEqual(payment_summary(self.order)["customer_due"], 1500)
        self.assertFalse(payment_summary(self.order)["settled"])

    def test_new_lender_receipt_is_available_for_reconciliation_without_fake_surplus(self):
        from sales.views import _decorate_reconciliation_record, _reconciliation_queryset
        from django.test import RequestFactory
        record = self.receipt(20000, receipt_kind="lender")
        request = RequestFactory().get("/", {"channel": "installment", "status": "pending"})
        self.assertIn(record.pk, _reconciliation_queryset(request).values_list("pk", flat=True))
        decorated = _decorate_reconciliation_record(record)
        self.assertEqual(decorated.reconciliation_channel, "installment")
        self.assertTrue(decorated.reconciliation_receipt_only)
        self.assertEqual(decorated.reconciliation_state, "已登記，待確認")

    def test_unauthorized_post_rejected(self):
        payload = self.payload()
        self.client.force_login(self.staff)
        response = self.client.post(reverse("order_operations", args=[self.order.pk]), payload, HTTP_X_ORDER_WORKSPACE="1")
        self.assertEqual(response.status_code, 403)

    def test_unknown_category_and_negative_receipt_rejected(self):
        from sales.forms import PaymentRecordForm
        form = PaymentRecordForm(data={"item_name": "錯誤輸入", "receipt_kind": "unknown", "received_amount": "-1"})
        self.assertFalse(form.is_valid())
        self.assertIn("receipt_kind", form.errors)
        self.assertIn("received_amount", form.errors)

    def test_migration_only_classifies_known_lender_preserving_values(self):
        import importlib
        from django.apps import apps
        from django.db import connection
        row = self.receipt(1234, confirmed=True)
        PaymentRecord.objects.filter(pk=row.pk).update(system_key="installment_disbursement")
        before = PaymentRecord.objects.filter(pk=row.pk).values().get()
        module = importlib.import_module("sales.migrations.0147_payment_receipt_kind")
        from types import SimpleNamespace
        module.classify_existing(apps, SimpleNamespace(connection=connection))
        after = PaymentRecord.objects.filter(pk=row.pk).values().get()
        self.assertEqual(after.pop("receipt_kind"), "lender")
        before.pop("receipt_kind")
        self.assertEqual(before, after)


class ReceiptConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update_nowait")
    def test_parallel_lender_receipts_do_not_lose_amounts(self):
        from threading import Barrier, Thread
        from django.db import close_old_connections, connection
        workspace_fixtures.OrderWorkspaceTests.setUpTestData.__func__(type(self))
        self.order.payment_type = "installment"
        self.order.installment_amount = 60000
        self.order.save()
        gate, errors = Barrier(2), []
        def receive(amount):
            close_old_connections()
            try:
                gate.wait(timeout=10)
                PaymentRecord.objects.create(order_id=self.order.pk, item_name="分批入帳", receipt_kind="lender",
                                             received_amount=amount, confirmed=True)
            except Exception as exc:
                errors.append(str(exc))
            finally:
                connection.close()
        workers = [Thread(target=receive, args=(amount,), daemon=True) for amount in (20000, 40000)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(20)
        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual(errors, [])
        self.assertEqual(OrderOperationsProfile.objects.get(order=self.order).actual_disbursement, 60000)
