"""退款證明與舊交車照片也能刪除（使用者 2026-11-06 選擇開放，比照其他上傳）。"""
from django.contrib.auth import get_user_model
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.access.registry import SCREENS
from sales.models import DeliveryRecord, OrderEvent, SalesOrder
from sales.tests import test_inplace_uploads as inplace
from sales.tests.test_inplace_uploads import png


class RefundHandoverDeleteTests(inplace.InplaceUploadTests.__bases__[0]):
    setUpClass = inplace.InplaceUploadTests.setUpClass
    tearDownClass = inplace.InplaceUploadTests.tearDownClass
    setUp = inplace.InplaceUploadTests.setUp
    detail = inplace.InplaceUploadTests.detail

    def url(self, kind):
        return reverse("order_file_delete", args=[self.order.pk, kind])

    def with_files(self):
        self.order.refund_proof = png("refund.png")
        self.order.save(update_fields=["refund_proof"])
        delivery = DeliveryRecord.objects.create(order=self.order, handover_photo=png("handover.png"))
        return delivery

    def test_both_deletable_with_event_and_file_cleanup(self):
        delivery = self.with_files()
        html = self.detail()
        for kind in ("refund_proof", "handover_photo"):
            self.assertIn(f'action="{self.url(kind)}" data-inplace-form data-confirm=', html)
        stored = (self.order.refund_proof.name, delivery.handover_photo.name)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.url("refund_proof"))
            self.client.post(self.url("handover_photo"))
        self.order.refresh_from_db()
        delivery.refresh_from_db()
        self.assertFalse(self.order.refund_proof)
        self.assertFalse(delivery.handover_photo)
        for name in stored:
            self.assertFalse(self.order.refund_proof.storage.exists(name))
        events = set(OrderEvent.objects.filter(order=self.order).values_list("event_type", flat=True))
        self.assertTrue({"refund_proof_deleted", "handover_photo_deleted"} <= events)

    def test_cancelled_order_refund_proof_still_deletable(self):
        self.with_files()
        SalesOrder.objects.filter(pk=self.order.pk).update(status=SalesOrder.Status.CANCELLED)
        self.client.post(self.url("refund_proof"))
        self.order.refresh_from_db()
        self.assertFalse(self.order.refund_proof)

    def test_get_and_unknown_kind_never_write(self):
        self.with_files()
        self.client.get(self.url("refund_proof"))
        self.assertEqual(self.client.post(self.url("signed_contract")).status_code, 404)
        self.order.refresh_from_db()
        self.assertTrue(self.order.refund_proof)

    def test_without_permission_no_button_and_post_blocked(self):
        self.with_files()
        viewer = get_user_model().objects.create_user("viewer2", password="test-pass-123")
        UserAccessState.objects.create(user=viewer, configured=True)
        ScreenAccessGrant.objects.bulk_create(
            ScreenAccessGrant(user=viewer, screen_key=screen.key, view=True, operate=screen.key != "work" and screen.operate)
            for screen in SCREENS)
        self.client.force_login(viewer)
        self.assertNotIn(self.url("refund_proof"), self.detail())
        self.client.post(self.url("refund_proof"))
        self.order.refresh_from_db()
        self.assertTrue(self.order.refund_proof)
