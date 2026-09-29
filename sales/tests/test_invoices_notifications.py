from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from sales.models import InvoiceRecord, Notification, OrderOperationsProfile, PaymentRecord, SalesOrder
from sales.services.invoices import allowance_invoice, invoice_attention, invoice_summary, issue_invoice, void_invoice
from sales.services.notifications import deliver_notification, notify, resend_pending
from sales.services.order_next_actions import build_order_next_actions
from sales.tests import test_order_lifecycle as lifecycle


class InvoiceTests(TestCase):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order
    confirm_deposit = lifecycle.OrderLifecycleTests.confirm_deposit

    def issue(self, order, number="ab-12345678", amount=70000):
        return issue_invoice(order_id=order.pk, actor_name="測試", invoice_number=number,
                             invoice_date=date(2026, 8, 5), amount=amount, buyer_tax_id="")

    def test_issue_normalizes_rejects_duplicates_and_syncs_profile(self):
        order, _vehicle = self.make_order()
        record = self.issue(order)
        self.assertEqual(record.invoice_number, "AB12345678")
        self.assertEqual(OrderOperationsProfile.objects.get(order=order).balance_invoice_number, "AB12345678")
        with self.assertRaisesMessage(ValidationError, "已登記過"):
            self.issue(order)
        with self.assertRaisesMessage(ValidationError, "格式"):
            self.issue(order, number="12345")
        with self.assertRaisesMessage(ValidationError, "統一編號"):
            issue_invoice(order_id=order.pk, actor_name="測試", invoice_number="AB00000001",
                          invoice_date=date(2026, 8, 5), amount=100, buyer_tax_id="123")

    def test_void_and_allowance_rules_and_immutability(self):
        order, _vehicle = self.make_order()
        first = self.issue(order)
        allowance_invoice(record_id=first.pk, actor_name="測試", invoice_date=date(2026, 8, 6), amount=5000, reason="折扣")
        with self.assertRaisesMessage(ValidationError, "不超過發票餘額 65,000"):
            allowance_invoice(record_id=first.pk, actor_name="測試", invoice_date=date(2026, 8, 6), amount=70000, reason="超額")
        with self.assertRaisesMessage(ValidationError, "已有折讓"):
            void_invoice(record_id=first.pk, actor_name="測試", invoice_date=date(2026, 8, 6), reason="作廢")
        second = self.issue(order, number="AB22222222", amount=1000)
        with self.assertRaisesMessage(ValidationError, "請填寫原因"):
            void_invoice(record_id=second.pk, actor_name="測試", invoice_date=date(2026, 8, 6), reason=" ")
        void_invoice(record_id=second.pk, actor_name="測試", invoice_date=date(2026, 8, 6), reason="開錯")
        with self.assertRaisesMessage(ValidationError, "已作廢"):
            void_invoice(record_id=second.pk, actor_name="測試", invoice_date=date(2026, 8, 6), reason="再作廢")
        self.assertEqual(invoice_summary(order)["net"], Decimal("65000"))
        first.amount = 1
        with self.assertRaises(ValidationError):
            first.save()
        with self.assertRaises(ValidationError):
            first.delete()

    def test_cancelled_order_with_open_invoice_is_flagged(self):
        order, _vehicle = self.make_order()
        self.confirm_deposit(order)
        self.issue(order, amount=5000)
        order.request_cancellation("測試", "客戶取消")
        order.complete_refund("測試", Decimal("0"), date(2026, 8, 6), SalesOrder.PaymentMethod.CASH)
        order.refresh_from_db()
        self.assertIn("未作廢或折讓", invoice_attention(order))
        actions = build_order_next_actions(order)
        self.assertEqual(actions.primary.key, "invoice")

    def test_invoice_endpoints(self):
        order, _vehicle = self.make_order()
        self.client.force_login(self.user)
        self.client.post(reverse("invoice_issue", args=[order.pk]), {
            "invoice_number": "CD12345678", "invoice_date": "2026-08-05", "amount": "70000", "return_to": "operations",
        })
        record = InvoiceRecord.objects.get(order=order)
        self.client.post(reverse("invoice_adjust", args=[order.pk]), {
            "action": "allowance", "invoice": record.pk, "invoice_date": "2026-08-06", "amount": "2000", "reason": "折讓",
        })
        self.assertEqual(invoice_summary(order)["net"], Decimal("68000"))
        page = self.client.get(reverse("order_operations", args=[order.pk]))
        self.assertContains(page, "CD12345678")


class NotificationTests(TestCase):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order
    confirm_deposit = lifecycle.OrderLifecycleTests.confirm_deposit

    def prepared_order(self, email=""):
        self.user.email = email
        self.user.save()
        order, _vehicle = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(accepted_by=self.user)
        order.refresh_from_db()
        return order

    def test_cancellation_notifies_after_commit_once(self):
        order = self.prepared_order()
        self.confirm_deposit(order)
        with self.captureOnCommitCallbacks(execute=True):
            order.request_cancellation("測試", "客戶取消")
        inbox = Notification.objects.filter(recipient=self.user, channel="in_app")
        self.assertEqual(inbox.count(), 1)
        self.assertIn("待退款結算", inbox.get().title)
        with self.captureOnCommitCallbacks(execute=True):
            notify("cancellation_refund_pending", order, "重複", dedupe_suffix=inbox.get().dedupe_key.split(":")[-1])
        self.assertEqual(inbox.count(), 1)
        self.client.force_login(self.user)
        page = self.client.get(reverse("notification_list"))
        self.assertContains(page, "待退款結算")
        self.client.post(reverse("notification_list"))
        self.assertFalse(inbox.filter(read_at__isnull=True).exists())

    def test_dealer_accounts_are_not_notified(self):
        from sales.models import OrderAccountProfile
        dealer_user = get_user_model().objects.create_user("dealer-account")
        OrderAccountProfile.objects.create(user=dealer_user, kind="dealer")
        order = self.prepared_order()
        SalesOrder.objects.filter(pk=order.pk).update(submitted_by=dealer_user)
        order.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            notify("test", order, "測試")
        self.assertFalse(Notification.objects.filter(recipient=dealer_user).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.user).exists())

    @override_settings(DMIS_NOTIFICATION_EMAIL_ENABLED=False, REDIS_URL="")
    def test_email_skipped_when_channel_not_configured(self):
        order = self.prepared_order(email="staff@example.test")
        with self.captureOnCommitCallbacks(execute=True):
            notify("test_event", order, "測試通知")
        email = Notification.objects.get(channel="email")
        self.assertEqual(email.status, Notification.Status.SKIPPED)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(DMIS_NOTIFICATION_EMAIL_ENABLED=True, REDIS_URL="",
                       EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_email_failure_retries_then_marks_failed_and_can_resend(self):
        order = self.prepared_order(email="staff@example.test")
        with patch("django.core.mail.send_mail", side_effect=OSError("smtp down")):
            with self.captureOnCommitCallbacks(execute=True):
                notify("test_event", order, "測試通知")
            email = Notification.objects.get(channel="email")
            self.assertEqual((email.status, email.attempts), (Notification.Status.PENDING, 1))
            deliver_notification(email.pk)
            deliver_notification(email.pk)
            email.refresh_from_db()
            self.assertEqual((email.status, email.attempts), (Notification.Status.FAILED, 3))
            self.assertIn("smtp down", email.last_error)
        self.assertEqual(resend_pending(), 1)
        email.refresh_from_db()
        self.assertEqual(email.status, Notification.Status.SENT)
        self.assertEqual(len(mail.outbox), 1)
