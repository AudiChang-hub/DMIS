"""其他保險單合成一個區塊、可一次多選上傳（使用者 2026-10-22 T-100）。

原本說明卡和灰底表單分開，像兩個要上傳的地方；改成標題下直接是上傳區、清單在同一塊，不寫「目前沒有」。
名稱不必填，自動帶原始檔名（去掉副檔名），清單上可直接改名；既有保險單照常顯示，上傳不卡領牌完成。
"""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from sales.models import OrderEvent, RegistrationDocument, SalesOrder
from sales.tests import test_inplace_uploads as inplace
from sales.tests.test_inplace_uploads import png

JSON = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest", "HTTP_ACCEPT": "application/json"}
OTHER = RegistrationDocument.DocumentType.OTHER_INSURANCE


class OtherInsuranceUploadTests(inplace.InplaceUploadTests.__bases__[0]):
    setUpClass = inplace.InplaceUploadTests.setUpClass
    tearDownClass = inplace.InplaceUploadTests.tearDownClass
    setUp = inplace.InplaceUploadTests.setUp
    detail = inplace.InplaceUploadTests.detail

    def upload(self, *files, **extra):
        return self.client.post(reverse("registration_document_upload", args=[self.order.pk]),
                                {"document_type": OTHER, "file": list(files)}, **extra)

    def section(self):
        html = self.detail()
        return html.split('data-multi-documents="other_insurance"', 1)[1].split("</section>", 1)[0]

    def insurance(self):
        return RegistrationDocument.objects.filter(order=self.order, document_type=OTHER)

    def test_one_block_with_upload_area_and_no_empty_text(self):
        section = self.section()
        self.assertEqual(section.count("<form"), 1)
        self.assertIn('id="other-insurance-upload" data-multi-upload', section)
        self.assertRegex(section, r'<input id="other-insurance-file" type="file" name="file" multiple')
        self.assertIn("data-upload-dropzone", section)
        self.assertNotIn('name="name"', section)
        self.assertNotIn("目前沒有", section)
        self.assertNotIn("新增其他保險單", section)

    def test_name_comes_from_file_and_many_files_saved_separately(self):
        response = self.upload(png("第三人責任險.png"), **JSON)
        self.assertTrue(response.json()["ok"])
        bad = SimpleUploadedFile("tool.exe", b"MZ\x90\x00", content_type="application/octet-stream")
        response = self.upload(png("車體險.2026.png"), bad, png("竊盜險.png"), **JSON)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("已上傳 2 份", payload["message"])
        self.assertIn("tool.exe", payload["message"])
        self.assertEqual(sorted(self.insurance().values_list("name", flat=True)), sorted(["第三人責任險", "竊盜險", "車體險.2026"]))

    def test_many_files_without_javascript_redirect_back(self):
        response = self.upload(png("a.png"), png("b.png"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.insurance().count(), 2)

    def test_rename_in_place_and_blank_falls_back(self):
        document = RegistrationDocument.objects.create(order=self.order, document_type=OTHER, name="IMG_2031", file=png())
        section = self.section()
        self.assertIn(f'action="{reverse("registration_document_rename", args=[self.order.pk, document.pk])}" data-inplace-form data-rename-form', section)
        self.assertIn('value="IMG_2031"', section)
        url = reverse("registration_document_rename", args=[self.order.pk, document.pk])
        self.assertEqual(self.client.post(url, {"name": "  第三人責任險 "}).status_code, 302)
        document.refresh_from_db()
        self.assertEqual(document.name, "第三人責任險")
        self.assertTrue(OrderEvent.objects.filter(order=self.order, event_type="registration_document_renamed").exists())
        self.client.post(url, {"name": ""})
        document.refresh_from_db()
        self.assertEqual((document.name, document.display_name), ("", "其他保險單"))

    def test_rename_only_for_other_insurance(self):
        license_doc = RegistrationDocument.objects.create(
            order=self.order, document_type=RegistrationDocument.DocumentType.NEW_LICENSE, name="行照", file=png())
        response = self.client.post(reverse("registration_document_rename", args=[self.order.pk, license_doc.pk]), {"name": "x"})
        self.assertEqual(response.status_code, 404)

    def test_existing_policies_still_listed(self):
        RegistrationDocument.objects.create(order=self.order, document_type=OTHER, name="舊保單", file=png())
        self.assertIn('value="舊保單"', self.section())

    def test_cancelled_order_without_policies_hides_block(self):
        SalesOrder.objects.filter(pk=self.order.pk).update(status=SalesOrder.Status.CANCELLED)
        self.assertNotIn('data-multi-documents="other_insurance"', self.detail())

    def test_other_registration_documents_share_rename_and_block(self):
        # 其他領牌相關資料（T-101）和其他保險單共用同一個區塊與改名流程，不留兩套。
        document = RegistrationDocument.objects.create(
            order=self.order, document_type=RegistrationDocument.DocumentType.OTHER, name="IMG_9", file=png())
        html = self.detail()
        other = html.split('data-multi-documents="other"', 1)[1].split("</section>", 1)[0]
        self.assertIn('id="other-registration-upload" data-multi-upload', other)
        self.assertIn(f'action="{reverse("registration_document_rename", args=[self.order.pk, document.pk])}"', other)
        self.client.post(reverse("registration_document_rename", args=[self.order.pk, document.pk]), {"name": "監理站收據"})
        document.refresh_from_db()
        self.assertEqual(document.name, "監理站收據")
