from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.access.services import AccessPolicy, snapshot
from sales.models import OrderAccountProfile, OrderEvent, PaymentRecord, SalesOrder, SalesSource, VehicleColor, VehicleModel
from sales.services.order_deletion import change_deletion, deletion_blockers


class OrderDeletionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = get_user_model().objects.create_superuser("admin", password="Local-delete-test-984!")
        cls.staff = get_user_model().objects.create_user("staff")
        cls.model = VehicleModel.objects.create(brand="QA", name="測試車", model_year=2026)
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="灰")

    def setUp(self):
        self.client.force_login(self.root)
        self.order = SalesOrder.objects.create(owner_name="回收測試", owner_phone="0900000000", owner_address="合成地址", owner_id_number="A123456789",
            vehicle_model=self.model, color=self.color, status=SalesOrder.Status.ALLOCATION_PENDING)

    def payload(self, **extra):
        return {"reason": "重複建立測試單", "confirmed": "on", "expected_updated_at": self.order.updated_at.isoformat(), **extra}

    def change(self, restore=False, **extra):
        return change_deletion(user=self.root, order_id=self.order.pk, restore=restore,
            reason="測試原因", expected_updated_at=self.order.updated_at.isoformat(), **extra)

    def test_delete_restore_preserve_business_data_and_audit(self):
        before = SalesOrder.objects.filter(pk=self.order.pk).values().get()
        self.assertContains(self.client.get(reverse("order_list")), reverse("order_delete", args=[self.order.pk]))
        self.assertEqual(self.client.post(reverse("order_delete", args=[self.order.pk]), self.payload()).status_code, 302)
        self.assertFalse(SalesOrder.objects.filter(pk=self.order.pk).exists())
        from sales.reporting.engine import base_query
        self.assertFalse(base_query({"date_basis": "established_on"}, {}).filter(pk=self.order.pk).exists())
        self.assertEqual(self.client.get(reverse("order_detail", args=[self.order.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("order_edit", args=[self.order.pk])).status_code, 404)
        self.assertContains(self.client.get(reverse("order_recycle_bin")), "重複建立測試單")
        self.assertNotContains(self.client.get(reverse("order_list")), self.order.number)
        self.order = SalesOrder.all_objects.get(pk=self.order.pk)
        self.assertEqual(self.order.deleted_by, "admin")
        self.assertEqual(self.client.post(reverse("order_restore", args=[self.order.pk]), self.payload(reason="誤刪還原")).status_code, 302)
        after = SalesOrder.objects.filter(pk=self.order.pk).values().get()
        for key in before.keys() - {"updated_at", "revision", "deleted_at", "deleted_by", "deletion_reason", "editing_session", "editing_by", "editing_at"}:
            self.assertEqual(before[key], after[key], key)
        self.assertEqual(list(OrderEvent.objects.filter(order=self.order, event_type__in=["soft_deleted", "restored"]).order_by("pk").values_list("event_type", flat=True)), ["soft_deleted", "restored"])

    def test_default_deny_explicit_grant_revoke_and_dealer_deny(self):
        self.assertFalse(AccessPolicy(self.staff).screen("order_delete"))
        self.assertFalse(snapshot(self.staff, [])["screens"]["order_delete"]["view"])
        self.client.force_login(self.staff)
        for name, args in [("order_recycle_bin", []), ("order_delete", [self.order.pk]), ("order_restore", [self.order.pk])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 403)
        UserAccessState.objects.create(user=self.staff, configured=True)
        grant = ScreenAccessGrant.objects.create(user=self.staff, screen_key="order_delete", view=True)
        self.assertEqual(self.client.get(reverse("order_recycle_bin")).status_code, 200)
        self.assertEqual(self.client.post(reverse("order_delete", args=[self.order.pk]), self.payload()).status_code, 403)
        grant.operate = True
        grant.save()
        self.assertEqual(self.client.get(reverse("order_delete", args=[self.order.pk])).status_code, 200)
        grant.operate = False
        grant.save()
        self.assertEqual(self.client.post(reverse("order_delete", args=[self.order.pk]), self.payload()).status_code, 403)
        source = SalesSource.objects.create(name="測試車行", source_type="dealer")
        OrderAccountProfile.objects.create(user=self.staff, kind="dealer", source=source)
        self.assertFalse(AccessPolicy(self.staff).screen("order_delete", "operate"))
        with self.assertRaises(PermissionDenied):
            change_deletion(user=self.staff, order_id=self.order.pk, restore=False, reason="測試", expected_updated_at=self.order.updated_at.isoformat())

    def test_confirmation_reason_csrf_methods_and_version(self):
        url = reverse("order_delete", args=[self.order.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertIsNone(SalesOrder.objects.get(pk=self.order.pk).deleted_at)
        for data in [self.payload(reason=" "), self.payload(confirmed=""), self.payload(expected_updated_at="old")]:
            self.assertEqual(self.client.post(url, data).status_code, 200)
            self.assertTrue(SalesOrder.objects.filter(pk=self.order.pk).exists())
        self.assertEqual(self.client.delete(url).status_code, 405)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.root)
        self.assertEqual(csrf.post(url, self.payload()).status_code, 403)
        self.change()
        with self.assertRaises(ValidationError):
            self.change()
        with self.assertRaises(ValidationError):
            self.order.save()

    def test_business_blockers_and_refunded_order(self):
        self.order.deposit_amount = Decimal("1000")
        self.order.balance_adjustment_reason = "測試訂金與退款保護"
        self.order.save()
        self.assertTrue(deletion_blockers(self.order))
        with self.assertRaises(ValidationError):
            self.change()
        self.order.status = SalesOrder.Status.CANCELLED
        self.order.refund_amount = Decimal("1000")
        self.order.refund_completed_on = timezone.localdate()
        self.order.save()
        self.assertFalse(deletion_blockers(self.order))
        payment_ids = list(self.order.payment_records.values_list("pk", flat=True))
        self.change()
        self.assertEqual(list(PaymentRecord.objects.filter(order_id=self.order.pk).values_list("pk", flat=True)), payment_ids)

    def test_registration_delivery_refund_and_editor_blockers(self):
        for fields in [{"registration_date": timezone.localdate()}, {"status": SalesOrder.Status.COMPLETED},
                       {"status": SalesOrder.Status.CANCEL_REFUND_PENDING}, {"final_plate_number": "QA-123"}]:
            order = SalesOrder.objects.get(pk=self.order.pk)
            for key, value in fields.items():
                setattr(order, key, value)
            self.assertTrue(deletion_blockers(order))
        SalesOrder.objects.filter(pk=self.order.pk).update(editing_session="other", editing_at=timezone.now())
        with self.assertRaises(ValidationError):
            self.change()
        SalesOrder.objects.filter(pk=self.order.pk).update(editing_at=timezone.now() - timedelta(minutes=5))
        self.change()

    def test_deleted_payment_media_hidden_and_recycle_search(self):
        payment = PaymentRecord.objects.create(order=self.order, item_name="證明", proof="private/not-opened.png")
        self.change()
        self.assertEqual(self.client.get(reverse("protected_media", args=["payment", payment.pk, "proof"])).status_code, 404)
        self.assertEqual(self.client.post(reverse("reconciliation_update", args=[payment.pk]), {}).status_code, 404)
        self.assertContains(self.client.get(reverse("order_recycle_bin"), {"q": "不存在"}), "共 0 筆")
        self.assertContains(self.client.get(reverse("order_recycle_bin"), {"q": self.order.number}), "共 1 筆")
        self.assertEqual(SalesOrder._base_manager.get(pk=self.order.pk).number, self.order.number)


@skipUnless(connection.vendor == "postgresql", "需要 PostgreSQL 行鎖")
class OrderDeletionConcurrencyTests(TransactionTestCase):
    def test_concurrent_delete_has_one_winner_and_one_audit_event(self):
        root = get_user_model().objects.create_superuser("admin", password="Concurrent-QA-only-42!")
        model = VehicleModel.objects.create(brand="QA", name="鎖定測試")
        color = VehicleColor.objects.create(vehicle_model=model, name="灰")
        order = SalesOrder.objects.create(owner_name="合成併發訂單", owner_phone="0900000000", owner_address="合成地址", owner_id_number="A123456789", vehicle_model=model, color=color)
        barrier = Barrier(2)
        def delete_once():
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=root.pk)
                barrier.wait(timeout=10)
                try:
                    change_deletion(user=user, order_id=order.pk, restore=False, reason="合成併發刪除", expected_updated_at=order.updated_at.isoformat())
                    return "done"
                except ValidationError:
                    return "conflict"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(delete_once) for _ in range(2)]
            self.assertCountEqual([f.result(timeout=30) for f in futures], ["done", "conflict"])
        self.assertEqual(OrderEvent.objects.filter(order=order, event_type="soft_deleted").count(), 1)
