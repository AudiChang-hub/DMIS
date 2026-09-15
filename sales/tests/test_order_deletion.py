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
from sales.services.order_deletion import change_deletion, deletion_blockers, review_deletion, confirmation_token


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

    def permit_staff(self):
        UserAccessState.objects.create(user=self.staff, configured=True)
        ScreenAccessGrant.objects.create(user=self.staff, screen_key="order_delete", view=True, operate=True)
        ScreenAccessGrant.objects.create(user=self.staff, screen_key="orders", view=True)

    def review(self, user, action, reason="匯入錯誤"):
        result = review_deletion(user=user, order_id=self.order.pk, action=action, reason=reason,
                                expected_updated_at=self.order.updated_at.isoformat())
        self.order.refresh_from_db()
        return result

    def force_delete(self):
        self.change(force=True, confirmation=confirmation_token(self.order, self.root))
        self.order = SalesOrder.all_objects.get(pk=self.order.pk)

    def test_request_cancel_reject_and_approve_keep_original_status(self):
        self.permit_staff()
        SalesOrder.objects.filter(pk=self.order.pk).update(status="completed")
        self.order.refresh_from_db()
        self.review(self.staff, "request")
        self.assertEqual((self.order.status, self.order.display_status), ("completed", "刪除確認中"))
        self.assertContains(self.client.get(reverse("order_deletion_queue")), "匯入錯誤")
        self.assertContains(self.client.get(reverse("order_list"), {"status": "deletion_pending"}), self.order.number)
        with self.assertRaises(ValidationError):
            self.review(self.staff, "request")
        self.review(self.staff, "cancel")
        self.assertEqual(self.order.display_status, "已完成")
        self.review(self.staff, "request")
        self.review(self.root, "reject", "資料仍需保留")
        self.assertIsNone(self.order.deletion_requested_at)
        self.review(self.staff, "request")
        self.force_delete()
        self.assertFalse(SalesOrder.objects.filter(pk=self.order.pk).exists())
        self.assertIsNone(self.order.deletion_requested_at)
        self.assertIn("匯入錯誤", OrderEvent.objects.filter(order=self.order, event_type="soft_deleted").get().description)

    def test_non_admin_cannot_force_delete_reject_or_cancel_someone_else(self):
        self.permit_staff()
        self.review(self.root, "request")
        for action in ("cancel", "reject"):
            with self.assertRaises(PermissionDenied):
                self.review(self.staff, action)
        with self.assertRaises(PermissionDenied):
            change_deletion(user=self.staff, order_id=self.order.pk, restore=False, reason="惡意繞過",
                expected_updated_at=self.order.updated_at.isoformat(), force=True)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("order_deletion_queue")).status_code, 403)
        self.assertEqual(self.client.post(reverse("order_delete", args=[self.order.pk]), self.payload(action="delete", force="on")).status_code, 403)

    def test_request_ui_cancel_and_stale_review(self):
        self.permit_staff()
        self.client.force_login(self.staff)
        url = reverse("order_delete", args=[self.order.pk])
        self.assertContains(self.client.get(url), "送出刪除申請")
        old = self.payload()
        self.assertEqual(self.client.post(url, old).status_code, 302)
        self.order.refresh_from_db()
        page = self.client.get(url)
        self.assertContains(page, "取消刪除申請")
        from html.parser import HTMLParser
        class Inputs(HTMLParser):
            values = {}
            def handle_starttag(parser, tag, attributes):
                attrs = dict(attributes)
                if tag == "input" and attrs.get("name"):
                    parser.values[attrs["name"]] = attrs.get("value", "")
        inputs = Inputs()
        inputs.feed(page.content.decode())
        self.assertEqual(inputs.values["expected_updated_at"], self.order.updated_at.isoformat())
        self.assertEqual(self.client.post(url, inputs.values).status_code, 302)
        with self.assertRaises(ValidationError):
            review_deletion(user=self.root, order_id=self.order.pk, action="reject", reason="檢查", expected_updated_at=old["expected_updated_at"])

    def test_force_keeps_receipts_but_removes_queries_and_requires_fresh_confirmation(self):
        payment = PaymentRecord.objects.create(order=self.order, item_name="合成實收", received_amount=1000)
        token = confirmation_token(self.order, self.root)
        PaymentRecord.objects.filter(pk=payment.pk).update(received_amount=2000)
        with self.assertRaisesMessage(ValidationError, "關聯已變更"):
            self.change(force=True, confirmation=token)
        self.force_delete()
        self.assertEqual(PaymentRecord.objects.get(pk=payment.pk).received_amount, 2000)
        self.assertIsNone(self.order.refund_completed_on)
        self.assertNotContains(self.client.get(reverse("reconciliation_list")), self.order.number)
        self.assertEqual(self.client.get(reverse("order_detail", args=[self.order.pk])).status_code, 404)

    def test_admin_completed_order_confirmation_form_executes_force_delete(self):
        SalesOrder.objects.filter(pk=self.order.pk).update(status="completed")
        self.order.refresh_from_db()
        url = reverse("order_delete", args=[self.order.pk])
        page = self.client.get(url)
        self.assertContains(page, "確認刪除訂單")
        self.assertTrue(page.context["form"].fields["force"].required)
        payload = self.payload(force="on", impact_confirmation=page.context["form"]["impact_confirmation"].value())
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertFalse(SalesOrder.objects.filter(pk=self.order.pk).exists())

    def make_inventory(self, status="reserved"):
        from sales.models import Store, VehicleInventory
        store = Store.objects.create(name="合成庫存門市")
        vehicle = VehicleInventory.objects.create(vehicle_model=self.model, color=self.color,
            ownership_store=store, location_store=store, status=status, frame_number="QA-DELETE-ONLY")
        SalesOrder.objects.filter(pk=self.order.pk).update(allocated_vehicle=vehicle)
        self.order.refresh_from_db()
        return vehicle

    def test_force_release_unregistered_vehicle_and_restore(self):
        vehicle = self.make_inventory()
        self.force_delete()
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, "available")
        self.assertIsNone(self.order.allocated_vehicle_id)
        self.change(restore=True)
        self.order = SalesOrder.objects.get(pk=self.order.pk)
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, "reserved")
        self.assertEqual(self.order.allocated_vehicle_id, vehicle.pk)

    def test_registered_vehicle_is_not_returned_as_new_stock_and_restore_conflict_is_atomic(self):
        from sales.models import VehicleInventory
        vehicle = self.make_inventory("sold")
        self.force_delete()
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, "inactive")
        VehicleInventory.objects.filter(pk=vehicle.pk).update(status="condition_issue")
        with self.assertRaisesMessage(ValidationError, "庫存車已異動"):
            self.change(restore=True)
        self.assertFalse(SalesOrder.objects.filter(pk=self.order.pk).exists())

    def test_bonus_allocation_void_and_restore_preserves_other_order_allocation(self):
        from datetime import date
        from sales.models import DealerVolumeBonusRule, DealerVolumeBonusTier, DealerVolumeBonusSettlement, DealerVolumeBonusAllocation
        dealer = SalesSource.objects.create(name="合成獎金車行", source_type="dealer")
        rule = DealerVolumeBonusRule.objects.create(dealer=dealer, starts_on=date(2026, 9, 1), ends_on=date(2026, 9, 30))
        DealerVolumeBonusTier.objects.create(rule=rule, minimum_quantity=1, bonus_per_vehicle=100)
        DealerVolumeBonusTier.objects.create(rule=rule, minimum_quantity=2, bonus_per_vehicle=200)
        settlement = DealerVolumeBonusSettlement.objects.create(rule=rule, dealer=dealer, qualified_quantity=2, expected_amount=400, actual_amount=400, bonus_per_vehicle=200)
        first = DealerVolumeBonusAllocation.objects.create(settlement=settlement, order=self.order, amount=200)
        other = SalesOrder.objects.create(owner_name="不得被轉嫁", owner_phone="0", owner_address="測試", owner_id_number="B123456789", vehicle_model=self.model, color=self.color)
        second = DealerVolumeBonusAllocation.objects.create(settlement=settlement, order=other, amount=200)
        self.force_delete()
        settlement.refresh_from_db()
        self.assertEqual((settlement.qualified_quantity, settlement.expected_amount, settlement.actual_amount), (1, 100, 200))
        self.assertEqual(DealerVolumeBonusAllocation.objects.get(pk=second.pk).amount, 200)
        self.assertFalse(DealerVolumeBonusAllocation.objects.filter(pk=first.pk).exists())
        self.assertTrue(DealerVolumeBonusAllocation.all_objects.filter(pk=first.pk).exists())
        self.change(restore=True)
        settlement.refresh_from_db()
        self.assertEqual((settlement.qualified_quantity, settlement.expected_amount, settlement.actual_amount), (2, 400, 400))
        self.assertEqual(settlement.adjustments.count(), 2)


@skipUnless(connection.vendor == "postgresql", "需要 PostgreSQL 行鎖")
class OrderDeletionConcurrencyTests(TransactionTestCase):
    def test_cancel_and_admin_approval_have_one_winner(self):
        root = get_user_model().objects.create_superuser("admin", password="Concurrent-QA-only-42!")
        staff = get_user_model().objects.create_user("requester")
        UserAccessState.objects.create(user=staff, configured=True)
        ScreenAccessGrant.objects.create(user=staff, screen_key="order_delete", view=True, operate=True)
        model = VehicleModel.objects.create(brand="QA", name="審核鎖定")
        color = VehicleColor.objects.create(vehicle_model=model, name="灰")
        order = SalesOrder.objects.create(owner_name="合成申請", owner_phone="0", owner_address="合成地址", owner_id_number="A123456789", vehicle_model=model, color=color, status="completed")
        review_deletion(user=staff, order_id=order.pk, action="request", reason="重複匯入", expected_updated_at=order.updated_at.isoformat())
        order.refresh_from_db()
        version, token = order.updated_at.isoformat(), confirmation_token(order, root)
        barrier = Barrier(2)
        def run(action):
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=root.pk if action == "approve" else staff.pk)
                barrier.wait(timeout=10)
                try:
                    if action == "approve":
                        change_deletion(user=user, order_id=order.pk, restore=False, reason="確認匯入錯誤", expected_updated_at=version, force=True, confirmation=token)
                    else:
                        review_deletion(user=user, order_id=order.pk, action="cancel", reason="取消", expected_updated_at=version)
                    return "done"
                except (ValidationError, SalesOrder.DoesNotExist):
                    return "conflict"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, action) for action in ("approve", "cancel")]
            self.assertCountEqual([item.result(timeout=30) for item in futures], ["done", "conflict"])

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
