"""內部通知 outbox：交易提交後才建立；Email 以背景佇列發送並記錄失敗、可重送。"""
import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3


def order_recipients(order):
    """接單人與內部下單人；車行與客戶帳號不接收內部財務通知。"""
    from sales.services.order_intake import is_dealer

    users = []
    for user in (getattr(order, "accepted_by", None), getattr(order, "submitted_by", None)):
        if user is None or not user.is_active or user in users or is_dealer(user):
            continue
        users.append(user)
    return users


def notify(event_key, order, title, body="", *, recipients=None, dedupe_suffix=""):
    """在交易提交後建立通知；同一事件同一收件人只建立一次。"""
    users = list(recipients) if recipients is not None else order_recipients(order)
    if not users:
        return

    def create():
        from sales.models import Notification

        for user in users:
            channels = [Notification.Channel.IN_APP]
            if user.email:
                channels.append(Notification.Channel.EMAIL)
            for channel in channels:
                key = f"{event_key}:{order.pk if order else 0}:{user.pk}:{channel}:{dedupe_suffix}"[:200]
                try:
                    with transaction.atomic():
                        notification = Notification.objects.create(
                            order=order, recipient=user, channel=channel, event_key=event_key, dedupe_key=key,
                            title=title[:160], body=body,
                            status=Notification.Status.SENT if channel == Notification.Channel.IN_APP else Notification.Status.PENDING,
                            sent_at=timezone.now() if channel == Notification.Channel.IN_APP else None,
                        )
                except IntegrityError:
                    continue
                if channel == Notification.Channel.EMAIL:
                    enqueue_delivery(notification.pk)

    transaction.on_commit(create)


def enqueue_delivery(notification_id):
    if not settings.REDIS_URL:
        deliver_notification(notification_id)
        return
    try:
        import django_rq

        django_rq.get_queue("notifications").enqueue(
            deliver_notification, notification_id, job_timeout=60, result_ttl=300, failure_ttl=86400,
        )
    except Exception:
        # 佇列不可用時保留待發送，交由管理指令或重送補發，不影響已完成的業務操作。
        logger.exception("通知無法排入背景佇列，保留待發送", extra={"notification_id": notification_id})


def deliver_notification(notification_id):
    """發送單筆 Email 通知；失敗累計次數，未達上限保持待發送供重試。"""
    from django.core.mail import send_mail
    from sales.models import Notification

    with transaction.atomic():
        notification = Notification.objects.select_for_update().filter(pk=notification_id).first()
        if notification is None or notification.status in {Notification.Status.SENT, Notification.Status.SKIPPED}:
            return notification
        if notification.channel != Notification.Channel.EMAIL:
            return notification
        if not settings.DMIS_NOTIFICATION_EMAIL_ENABLED:
            notification.status = Notification.Status.SKIPPED
            notification.last_error = "尚未設定 Email 發送通道"
            notification.save(update_fields=["status", "last_error", "updated_at"])
            return notification
        notification.attempts += 1
        try:
            send_mail(notification.title, notification.body or notification.title,
                      getattr(settings, "DEFAULT_FROM_EMAIL", None), [notification.recipient.email])
        except Exception as exc:
            notification.last_error = str(exc)[:500]
            notification.status = (
                Notification.Status.FAILED if notification.attempts >= MAX_ATTEMPTS else Notification.Status.PENDING
            )
            notification.save(update_fields=["attempts", "last_error", "status", "updated_at"])
            logger.warning("通知發送失敗", extra={"notification_id": notification_id, "attempts": notification.attempts})
            return notification
        notification.status = Notification.Status.SENT
        notification.sent_at = timezone.now()
        notification.last_error = ""
        notification.save(update_fields=["attempts", "status", "sent_at", "last_error", "updated_at"])
        return notification


def resend_pending(limit=200):
    """補發待發送或失敗的 Email 通知（管理指令與管理頁共用）。"""
    from sales.models import Notification

    ids = list(Notification.objects.filter(
        channel=Notification.Channel.EMAIL,
        status__in=[Notification.Status.PENDING, Notification.Status.FAILED],
    ).order_by("pk").values_list("pk", flat=True)[:limit])
    for notification_id in ids:
        Notification.objects.filter(pk=notification_id, status=Notification.Status.FAILED).update(
            status=Notification.Status.PENDING, attempts=0,
        )
        deliver_notification(notification_id)
    return len(ids)
