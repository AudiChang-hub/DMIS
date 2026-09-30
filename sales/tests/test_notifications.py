from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from sales.models import Notification, SalesOrder
from sales.services.notifications import deliver_notification, notify, resend_pending
from sales.tests import test_order_lifecycle as lifecycle


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
