"""每個上傳的位置都要能刪（使用者 2026-11-06 T-121）。

領牌文件與其他保險單在領牌完成後仍可刪除、替換（取消或例外結案才鎖）；附件分頁的文件格與下訂附件也能刪；
刪除前確認、留處理紀錄、清掉實體檔；沒權限看不到刪除鈕、直接 POST 也會被擋；GET 不寫入；刪除不卡流程。
"""
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.access.registry import SCREENS
from sales.models import OrderAttachment, OrderEvent, OrderIntakeAttachment, RegistrationDocument, SalesOrder, SubsidyDocument
from sales.tests import test_inplace_uploads as inplace
from sales.tests.test_inplace_uploads import png


class UploadDeleteTests(inplace.InplaceUploadTests.__bases__[0]):
    setUpClass = inplace.InplaceUploadTests.setUpClass
    tearDownClass = inplace.InplaceUploadTests.tearDownClass
    setUp = inplace.InplaceUploadTests.setUp
    detail = inplace.InplaceUploadTests.detail

    def complete_registration(self):
        SalesOrder.objects.filter(pk=self.order.pk).update(registration_completed_at=timezone.now())
        self.order.refresh_from_db()

    def registration_doc(self, document_type=RegistrationDocument.DocumentType.INVOICE, name=""):
        return RegistrationDocument.objects.create(order=self.order, document_type=document_type, name=name, file=png("doc.png"))

    def delete_url(self, document):
        return reverse("registration_document_delete", args=[self.order.pk, document.pk])

    def test_registration_document_deletable_after_completion(self):
        self.complete_registration()
        document = self.registration_doc()
        stored = document.file.name
        self.assertIn(f'action="{self.delete_url(document)}"', self.detail())
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.delete_url(document))
        self.assertFalse(RegistrationDocument.objects.filter(pk=document.pk).exists())
        self.assertFalse(document.file.storage.exists(stored))
        self.assertTrue(OrderEvent.objects.filter(order=self.order, event_type="registration_document_deleted").exists())
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_registration_complete, "刪除不會讓領牌回到未完成")

    def test_registration_document_replaceable_after_completion(self):
        self.complete_registration()
        self.registration_doc()
        response = self.client.post(reverse("registration_document_upload", args=[self.order.pk]),
                                    {"document_type": RegistrationDocument.DocumentType.INVOICE, "file": png("new.png")},
                                    HTTP_X_REQUESTED_WITH="XMLHttpRequest", HTTP_ACCEPT="application/json")
        self.assertTrue(response.json()["ok"])
        self.assertEqual(RegistrationDocument.objects.filter(order=self.order, document_type="invoice").count(), 1)

    def test_other_insurance_deletable_after_completion(self):
        self.complete_registration()
        document = self.registration_doc(RegistrationDocument.DocumentType.OTHER_INSURANCE, "車體險")
        self.client.post(self.delete_url(document))
        self.assertFalse(RegistrationDocument.objects.filter(pk=document.pk).exists())

    def test_cancelled_order_locks_delete(self):
        document = self.registration_doc()
        SalesOrder.objects.filter(pk=self.order.pk).update(status=SalesOrder.Status.CANCELLED)
        self.client.post(self.delete_url(document))
        self.assertTrue(RegistrationDocument.objects.filter(pk=document.pk).exists())

    def test_attachments_tab_slots_and_intake_files_have_delete(self):
        self.complete_registration()
        document = self.registration_doc()
        intake = OrderIntakeAttachment.objects.create(order=self.order, uploaded_by=self.user, kind="supplement", name="分期表.png", file=png("i.png"))
        html = self.detail()
        self.assertIn(f'action="{self.delete_url(document)}" data-inplace-form data-confirm=', html)
        intake_url = reverse("order_intake_attachment_delete", args=[self.order.pk, intake.pk])
        self.assertIn(f'action="{intake_url}" data-inplace-form data-confirm=', html)
        stored = intake.file.name
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(intake_url)
        self.assertFalse(OrderIntakeAttachment.objects.filter(pk=intake.pk).exists())
        self.assertFalse(intake.file.storage.exists(stored))
        self.assertTrue(OrderEvent.objects.filter(order=self.order, event_type="order_intake_attachment_deleted").exists())

    def test_other_attachment_delete_removes_file(self):
        attachment = OrderAttachment.objects.create(order=self.order, name="a.png", file=png("a.png"))
        stored = attachment.file.name
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("order_attachment_delete", args=[self.order.pk, attachment.pk]))
        self.assertFalse(attachment.file.storage.exists(stored))

    def test_get_never_deletes(self):
        document = self.registration_doc()
        intake = OrderIntakeAttachment.objects.create(order=self.order, uploaded_by=self.user, kind="supplement", name="x.png", file=png("x.png"))
        subsidy = SubsidyDocument.objects.create(order=self.order, document_type="other", name="切結書", file=png("s.png"))
        for url in (self.delete_url(document),
                    reverse("order_intake_attachment_delete", args=[self.order.pk, intake.pk]),
                    reverse("subsidy_document_delete", args=[self.order.pk, subsidy.pk])):
            self.client.get(url)
        self.assertTrue(RegistrationDocument.objects.filter(pk=document.pk).exists())
        self.assertTrue(OrderIntakeAttachment.objects.filter(pk=intake.pk).exists())
        self.assertTrue(SubsidyDocument.objects.filter(pk=subsidy.pk).exists())

    def test_without_permission_no_button_and_post_blocked(self):
        viewer = get_user_model().objects.create_user("viewer", password="test-pass-123")
        UserAccessState.objects.create(user=viewer, configured=True)
        ScreenAccessGrant.objects.bulk_create(
            ScreenAccessGrant(user=viewer, screen_key=screen.key, view=True, operate=screen.key != "work" and screen.operate)
            for screen in SCREENS)
        document = self.registration_doc()
        intake = OrderIntakeAttachment.objects.create(order=self.order, uploaded_by=self.user, kind="supplement", name="y.png", file=png("y.png"))
        self.client.force_login(viewer)
        html = self.detail()
        self.assertNotIn(self.delete_url(document), html)
        self.assertNotIn(reverse("order_intake_attachment_delete", args=[self.order.pk, intake.pk]), html)
        self.client.post(self.delete_url(document))
        self.client.post(reverse("order_intake_attachment_delete", args=[self.order.pk, intake.pk]))
        self.assertTrue(RegistrationDocument.objects.filter(pk=document.pk).exists())
        self.assertTrue(OrderIntakeAttachment.objects.filter(pk=intake.pk).exists())
