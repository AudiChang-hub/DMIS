"""其他補助文件一次多選、拖曳多檔上傳（使用者 2026-10-22 T-94）。

拿掉「文件名稱」「備註」輸入；名稱自動帶原始檔名（去掉副檔名），每個檔案各存一筆、各自檢查。
既有文件的名稱與備註照常顯示；資料庫結構不變。
"""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from sales.models import SalesOrder, SubsidyDocument
from sales.tests import test_inplace_uploads as inplace
from sales.tests.test_inplace_uploads import png

JSON = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest", "HTTP_ACCEPT": "application/json"}


class OtherSubsidyMultiUploadTests(inplace.InplaceUploadTests.__bases__[0]):
    setUpClass = inplace.InplaceUploadTests.setUpClass
    tearDownClass = inplace.InplaceUploadTests.tearDownClass
    setUp = inplace.InplaceUploadTests.setUp
    detail = inplace.InplaceUploadTests.detail

    def upload(self, *files, **extra):
        return self.client.post(reverse("subsidy_document_upload", args=[self.order.pk]),
                                {"document_type": "other", "file": list(files)}, **extra)

    def other_section(self):
        html = self.detail()
        return html, html.split('class="other-subsidy-documents"', 1)[1].split("</section>", 1)[0]

    def test_form_takes_many_files_without_name_or_note(self):
        html, section = self.other_section()
        self.assertRegex(section, r'<input id="other-subsidy-file" type="file" name="file" multiple')
        self.assertIn("data-multi-upload", section)
        self.assertIn("data-upload-dropzone", section)
        self.assertNotIn('name="name"', section)
        self.assertNotIn('name="note"', section)
        self.assertNotIn("文件名稱", section)
        self.assertIn("可一次選多個檔案", section)
        self.assertIn("js/other-subsidy-upload.js", html)

    def test_single_upload_names_document_after_file(self):
        response = self.upload(png("補助切結書.png"), **JSON)
        self.assertTrue(response.json()["ok"])
        document = SubsidyDocument.objects.get(order=self.order, document_type="other")
        self.assertEqual((document.name, document.note), ("補助切結書", ""))

    def test_many_files_each_saved_and_checked_on_their_own(self):
        bad = SimpleUploadedFile("tool.exe", b"MZ\x90\x00", content_type="application/octet-stream")
        response = self.upload(png("加碼申請.png"), bad, png("切結書.final.png"), **JSON)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("已上傳 2 份", payload["message"])
        self.assertIn("tool.exe", payload["message"])
        names = sorted(SubsidyDocument.objects.filter(order=self.order).values_list("name", flat=True))
        self.assertEqual(names, ["切結書.final", "加碼申請"])

    def test_many_files_without_javascript_redirect_back(self):
        response = self.upload(png("a.png"), png("b.png"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SubsidyDocument.objects.filter(order=self.order).count(), 2)

    def test_oversized_file_rejected(self):
        big = SimpleUploadedFile("big.pdf", b"%PDF-1.4\n" + b"0" * (20 * 1024 * 1024 + 1), content_type="application/pdf")
        response = self.upload(big, **JSON)
        self.assertFalse(response.json()["ok"])
        self.assertFalse(SubsidyDocument.objects.filter(order=self.order).exists())

    def test_existing_name_and_note_still_shown(self):
        SubsidyDocument.objects.create(order=self.order, document_type="other", name="舊切結書", note="正本已寄回",
                                       file=png("old.png"))
        _html, section = self.other_section()
        self.assertIn("舊切結書", section)
        self.assertIn("正本已寄回", section)

    def test_other_documents_upload_without_trade_in(self):
        # 畫面上不論有沒有汰舊都能上傳其他補助文件（T-83）；固定文件仍限汰舊／政府補助的訂單。
        SalesOrder.objects.filter(pk=self.order.pk).update(is_trade_in_subsidy=False)
        self.assertTrue(self.upload(png("加碼.png"), **JSON).json()["ok"])
        fixed = self.client.post(reverse("subsidy_document_upload", args=[self.order.pk]),
                                 {"document_type": SubsidyDocument.DocumentType.SCRAP_CERTIFICATE, "file": png()}, **JSON)
        self.assertEqual(fixed.status_code, 400)
