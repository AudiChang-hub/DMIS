"""訂單「附件」分頁：其他附件（任何檔案、每單 50 個）與全部檔案集中預覽。"""
import tempfile
import zipfile
from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from sales.models import OrderAttachment, OrderEvent, RegistrationDocument
from sales.services.order_intake import DEALER_ROUTES
from sales.services.order_steps import order_step_url
from sales.tests import test_order_lifecycle as lifecycle


def png_bytes():
    stream = BytesIO()
    Image.new("RGB", (8, 8), "white").save(stream, format="PNG")
    return stream.getvalue()


class OrderAttachmentTests(TestCase):
    make_order = lifecycle.OrderLifecycleTests.make_order

    def setUp(self):
        lifecycle.OrderLifecycleTests.setUp(self)
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        override = override_settings(MEDIA_ROOT=self.media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.order, _vehicle = self.make_order(deposit=Decimal("5000"))
        self.client.force_login(self.user)
        self.upload_url = reverse("order_attachment_upload", args=[self.order.pk])

    def upload(self, *files, ajax=False, **data):
        headers = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"} if ajax else {}
        return self.client.post(self.upload_url, {"files": list(files), **data}, **headers)

    def test_any_file_types_upload_together_with_note_and_event(self):
        response = self.upload(
            SimpleUploadedFile("報價單 (最終).xlsx", b"PK\x03\x04 sheet"),
            SimpleUploadedFile("錄音.m4a", b"\x00\x00\x00 audio"),
            SimpleUploadedFile("photo.PNG", png_bytes(), content_type="image/png"),
            note="客戶補件",
        )

        self.assertRedirects(response, order_step_url(self.order.pk, "attachments"), fetch_redirect_response=False)
        attachments = list(self.order.other_attachments.all())
        self.assertEqual([a.name for a in attachments], ["報價單 (最終).xlsx", "錄音.m4a", "photo.PNG"])
        self.assertTrue(all(a.note == "客戶補件" and a.uploaded_by for a in attachments))
        # 儲存檔名改用亂數，原始檔名只存在 name 欄位。
        self.assertNotIn("報價單", attachments[0].file.name)
        self.assertTrue(attachments[0].file.name.endswith(".xlsx"))
        event = OrderEvent.objects.get(order=self.order, event_type="order_attachment_uploaded")
        self.assertIn("報價單 (最終).xlsx", event.description)

    def test_limit_is_fifty_per_order(self):
        for index in range(OrderAttachment.MAX_PER_ORDER - 1):
            OrderAttachment.objects.create(
                order=self.order, name=f"{index}.txt", file=SimpleUploadedFile(f"{index}.txt", b"x"),
            )

        response = self.upload(
            SimpleUploadedFile("a.txt", b"a"), SimpleUploadedFile("b.txt", b"b"), ajax=True,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("最多還能上傳 1 個", response.json()["message"])
        self.assertEqual(self.order.other_attachments.count(), 49)

        self.assertEqual(self.upload(SimpleUploadedFile("a.txt", b"a"), ajax=True).status_code, 200)
        self.assertEqual(self.order.other_attachments.count(), 50)
        page = self.client.get(reverse("order_detail", args=[self.order.pk])).content.decode()
        self.assertIn("已達 50 個上限", page)

    def test_empty_and_oversized_files_are_rejected(self):
        response = self.upload(SimpleUploadedFile("empty.txt", b""), ajax=True)
        self.assertEqual(response.status_code, 400)
        self.assertIn("empty.txt", response.json()["message"])
        big = SimpleUploadedFile("big.bin", b"0" * (20 * 1024 * 1024 + 1))
        response = self.upload(big, ajax=True)
        self.assertEqual(response.status_code, 400)
        self.assertIn("20 MB", response.json()["message"])
        self.assertFalse(self.order.other_attachments.exists())

    def test_only_images_and_pdfs_open_inline_everything_else_downloads(self):
        self.upload(
            SimpleUploadedFile("page.html", b"<script>alert(1)</script>", content_type="text/html"),
            SimpleUploadedFile("photo.png", png_bytes(), content_type="image/png"),
        )
        html, photo = self.order.other_attachments.all()

        response = self.client.get(reverse("order_attachment_file", args=[html.pk]), {"preview": "1"})
        self.addCleanup(response.close)
        self.assertTrue(response["Content-Disposition"].startswith("attachment"))
        self.assertIn("page.html", response["Content-Disposition"])
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

        response = self.client.get(reverse("order_attachment_file", args=[photo.pk]), {"preview": "1"})
        self.addCleanup(response.close)
        self.assertTrue(response["Content-Disposition"].startswith("inline"))
        self.assertEqual(response["Content-Type"], "image/png")

    def test_delete_removes_record_and_logs_event(self):
        self.upload(SimpleUploadedFile("note.txt", b"hello"))
        attachment = self.order.other_attachments.get()

        response = self.client.post(reverse("order_attachment_delete", args=[self.order.pk, attachment.pk]))

        self.assertRedirects(response, order_step_url(self.order.pk, "attachments"), fetch_redirect_response=False)
        self.assertFalse(self.order.other_attachments.exists())
        self.assertTrue(OrderEvent.objects.filter(order=self.order, event_type="order_attachment_deleted").exists())

    def test_attachments_tab_gathers_files_from_every_step(self):
        RegistrationDocument.objects.create(
            order=self.order,
            document_type=RegistrationDocument.DocumentType.NEW_LICENSE,
            file=SimpleUploadedFile("license.png", png_bytes(), content_type="image/png"),
            uploaded_by="行政",
        )
        self.upload(SimpleUploadedFile("合約掃描.docx", b"PK\x03\x04 doc"))

        page = self.client.get(reverse("order_detail", args=[self.order.pk]), {"tab": "attachments"}).content.decode()

        panel = page.split('id="panel-attachments"', 1)[1].split('id="panel-history"', 1)[0]
        self.assertIn("is-active", page.split('id="panel-attachments"', 1)[0].rsplit("<section", 1)[1])
        self.assertIn("領牌文件", panel)
        self.assertIn("新行照照片", panel)
        self.assertIn(reverse("registration_document_file", args=[self.order.registration_documents.get().pk]), panel)
        # 不可預覽的檔案直接顯示副檔名卡片與下載連結。
        self.assertIn(">DOCX<", panel)
        self.assertIn('download="合約掃描.docx"', panel)
        self.assertIn("1／50", panel)

    def test_dealer_accounts_cannot_reach_attachment_routes(self):
        for name in ("order_attachment_upload", "order_attachment_delete", "order_attachment_file", "order_attachments_zip"):
            self.assertNotIn(name, DEALER_ROUTES)

    def download_zip(self):
        response = self.client.get(reverse("order_attachments_zip", args=[self.order.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertIn(".zip", response["Content-Disposition"])
        self.assertTrue(response["Content-Disposition"].startswith("attachment"))
        data = b"".join(response.streaming_content)
        response.close()
        return zipfile.ZipFile(BytesIO(data))

    def test_download_all_packs_every_file_into_category_folders(self):
        RegistrationDocument.objects.create(
            order=self.order,
            document_type=RegistrationDocument.DocumentType.NEW_LICENSE,
            file=SimpleUploadedFile("license.png", png_bytes(), content_type="image/png"),
        )
        self.upload(
            SimpleUploadedFile("報價單.xlsx", b"PK\x03\x04 sheet"),
            SimpleUploadedFile("報價單.xlsx", b"second copy"),
            SimpleUploadedFile("備註.txt", b"hello"),
        )

        archive = self.download_zip()

        names = archive.namelist()
        self.assertIn("其他附件/報價單.xlsx", names)
        self.assertIn("其他附件/報價單_2.xlsx", names)
        self.assertIn("領牌文件/新行照照片.png", names)
        self.assertEqual(archive.read("其他附件/備註.txt"), b"hello")
        self.assertEqual(archive.read("其他附件/報價單_2.xlsx"), b"second copy")
        self.assertEqual(archive.getinfo("領牌文件/新行照照片.png").compress_type, zipfile.ZIP_STORED)
        self.assertNotIn("缺少的檔案.txt", names)
        page = self.client.get(reverse("order_detail", args=[self.order.pk])).content.decode()
        self.assertIn(reverse("order_attachments_zip", args=[self.order.pk]), page)

    def test_download_all_lists_files_missing_from_storage(self):
        self.upload(SimpleUploadedFile("在.txt", b"ok"), SimpleUploadedFile("不見了.txt", b"gone"))
        lost = self.order.other_attachments.get(name="不見了.txt")
        lost.file.storage.delete(lost.file.name)

        archive = self.download_zip()

        self.assertIn("其他附件/在.txt", archive.namelist())
        self.assertNotIn("其他附件/不見了.txt", archive.namelist())
        self.assertIn("不見了.txt", archive.read("缺少的檔案.txt").decode())

    def test_download_all_without_files_returns_to_tab(self):
        response = self.client.get(reverse("order_attachments_zip", args=[self.order.pk]))

        self.assertRedirects(response, order_step_url(self.order.pk, "attachments"), fetch_redirect_response=False)
        page = self.client.get(reverse("order_detail", args=[self.order.pk])).content.decode()
        self.assertNotIn(reverse("order_attachments_zip", args=[self.order.pk]), page)


class RequiredDocumentSlotTests(TestCase):
    """附件分頁的「該上傳的文件」清單與「歸類到…」（使用者 2026-10-14 選 A＋B）。"""

    make_order = lifecycle.OrderLifecycleTests.make_order
    setUp = OrderAttachmentTests.setUp
    upload = OrderAttachmentTests.upload

    def tab(self):
        page = self.client.get(reverse("order_detail", args=[self.order.pk]), {"tab": "attachments"}).content.decode()
        return page.split('id="panel-attachments"', 1)[1].split('id="panel-history"', 1)[0]

    def add_attachment(self, name, data):
        self.upload(SimpleUploadedFile(name, data))
        return self.order.other_attachments.get(name=name)

    def classify(self, attachment, target):
        return self.client.post(
            reverse("order_attachment_classify", args=[self.order.pk, attachment.pk]), {"target": target},
        )

    def test_checklist_lists_every_step_slot_with_upload_back_to_tab(self):
        panel = self.tab()

        required = panel.split('id="required-documents"', 1)[1].split('id="other-attachments"', 1)[0]
        for text in ("簽署文件", "訂購合約", "個資同意書", "領牌文件", "新行照照片", "新車領牌登記書", "選號單"):
            self.assertIn(text, required)
        self.assertIn(reverse("registration_document_upload", args=[self.order.pk]), required)
        self.assertIn(reverse("contract_upload", args=[self.order.pk]), required)
        self.assertIn('name="return_tab" value="attachments"', required)
        self.assertIn("還缺", required)
        # 未勾選補助時不列補助文件。
        self.assertNotIn("補助文件", required)

    def test_upload_from_checklist_returns_to_attachments_tab(self):
        response = self.client.post(
            reverse("registration_document_upload", args=[self.order.pk]),
            {
                "document_type": RegistrationDocument.DocumentType.NEW_LICENSE,
                "return_tab": "attachments",
                "file": SimpleUploadedFile("license.png", png_bytes(), content_type="image/png"),
            },
        )

        self.assertRedirects(
            response, order_step_url(self.order.pk, "attachments", "required-documents"),
            fetch_redirect_response=False,
        )
        self.assertTrue(self.order.registration_documents.filter(document_type="new_license").exists())

    def test_classify_moves_attachment_into_registration_slot(self):
        attachment = self.add_attachment("行照.png", png_bytes())

        response = self.classify(attachment, "registration:new_license")

        self.assertRedirects(
            response, order_step_url(self.order.pk, "attachments", "required-documents"),
            fetch_redirect_response=False,
        )
        document = self.order.registration_documents.get(document_type="new_license")
        self.assertEqual(document.file.read(), png_bytes())
        document.file.close()
        self.assertFalse(self.order.other_attachments.exists())
        event = OrderEvent.objects.get(order=self.order, event_type="order_attachment_classified")
        self.assertIn("行照.png", event.description)
        self.assertIn("新行照照片", event.description)
        self.assertTrue(OrderEvent.objects.filter(order=self.order, event_type="registration_document_uploaded").exists())

    def test_classify_replaces_existing_slot_file(self):
        RegistrationDocument.objects.create(
            order=self.order, document_type="new_license",
            file=SimpleUploadedFile("old.png", png_bytes(), content_type="image/png"),
        )
        attachment = self.add_attachment("新的.pdf", self.pdf_bytes())

        self.classify(attachment, "registration:new_license")

        document = self.order.registration_documents.get(document_type="new_license")
        self.assertTrue(document.file.name.endswith(".pdf"))
        self.assertEqual(self.order.registration_documents.filter(document_type="new_license").count(), 1)

    def test_classify_to_contract_records_paper_signature(self):
        attachment = self.add_attachment("合約.pdf", self.pdf_bytes())

        self.classify(attachment, "contract")

        self.order.refresh_from_db()
        self.assertTrue(self.order.has_signed_contract)
        self.assertFalse(self.order.signed_contract_is_electronic)
        self.assertFalse(self.order.other_attachments.exists())

    def test_classify_failure_keeps_attachment_and_explains(self):
        attachment = self.add_attachment("報價單.xlsx", b"PK\x03\x04 sheet")

        response = self.classify(attachment, "registration:new_license")

        self.assertRedirects(
            response, order_step_url(self.order.pk, "attachments", "other-attachments"),
            fetch_redirect_response=False,
        )
        self.assertTrue(self.order.other_attachments.filter(pk=attachment.pk).exists())
        self.assertFalse(self.order.registration_documents.exists())
        messages = [str(m) for m in response.wsgi_request._messages]
        self.assertTrue(any("無法歸類" in m for m in messages), messages)

    def test_classify_rejects_unknown_target(self):
        attachment = self.add_attachment("a.png", png_bytes())

        self.classify(attachment, "registration:not_a_type")

        self.assertTrue(self.order.other_attachments.filter(pk=attachment.pk).exists())

    def test_dropdown_only_offers_slots_that_accept_the_file(self):
        self.add_attachment("照片.png", png_bytes())
        self.add_attachment("報價單.xlsx", b"PK\x03\x04 sheet")

        panel = self.tab()

        image_card = panel.split("照片.png", 1)[1].split("報價單.xlsx", 1)[0]
        self.assertIn('value="registration:new_license"', image_card)
        self.assertIn('value="contract"', image_card)
        sheet_card = panel.split("報價單.xlsx", 1)[1].split('id="all-order-files"', 1)[0]
        # 領牌與簽署文件只收圖片／PDF；未開補助時 Excel 沒有可歸類的格，不顯示選單。
        self.assertNotIn("data-classify-form", sheet_card)

    def test_subsidy_slots_accept_non_image_files_when_subsidy_enabled(self):
        from sales.models import SalesOrder
        SalesOrder.objects.filter(pk=self.order.pk).update(is_trade_in_subsidy=True)
        attachment = self.add_attachment("舊車行照.csv", "車牌,ABC-123\n".encode())

        panel = self.tab()
        self.assertIn("補助文件", panel.split('id="required-documents"', 1)[1].split('id="other-attachments"', 1)[0])
        card = panel.split("舊車行照.csv", 1)[1].split('id="all-order-files"', 1)[0]
        self.assertIn('value="subsidy:old_vehicle_registration"', card)
        self.assertNotIn('value="registration:new_license"', card)

        self.classify(attachment, "subsidy:old_vehicle_registration")

        self.assertTrue(self.order.subsidy_documents.filter(document_type="old_vehicle_registration").exists())
        self.assertFalse(self.order.other_attachments.exists())

    def test_dealer_cannot_reach_classify_route(self):
        self.assertNotIn("order_attachment_classify", DEALER_ROUTES)

    @staticmethod
    def pdf_bytes():
        from pypdf import PdfWriter

        stream = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.write(stream)
        return stream.getvalue()
