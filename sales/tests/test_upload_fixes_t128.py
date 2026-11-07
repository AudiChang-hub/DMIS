"""11/7 UAT（T-128）：建單附件改成可刪除、替換的附件卡；替換後縮圖換新；沒有汰舊也能上傳補助文件。"""
from pathlib import Path

from django.test import override_settings
from django.urls import reverse

from sales.models import OrderDraft, OrderIntakeAttachment, SalesOrder, SubsidyDocument
from sales.tests import test_drafts as drafts
from sales.tests import test_inplace_uploads as inplace
from sales.tests.test_inplace_uploads import png


class IntakeUploadCardTests(drafts.OrderDraftTests.__bases__[0]):
    setUp = drafts.OrderDraftTests.setUp
    image = drafts.OrderDraftTests.image
    complete_data = drafts.OrderDraftTests.complete_data

    def distinct(self, name):
        from io import BytesIO
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        stream = BytesIO()
        Image.new("RGB", (6, 6), "red").save(stream, format="PNG")
        return SimpleUploadedFile(name, stream.getvalue(), content_type="image/png")

    def test_draft_save_lists_saved_attachments_and_removal(self):
        response = self.client.post(reverse("draft_save"), {
            **self.complete_data(), "installment_document": self.image("分期表.png"),
            "supplement_documents": [png("a.png"), self.distinct("b.png")]})
        payload = response.json()
        names = sorted(item["name"] for item in payload["attachments"])
        self.assertEqual(names, ["a.png", "b.png", "分期表.png"])
        self.assertEqual({item["kind"] for item in payload["attachments"]}, {"installment", "supplement"})
        draft = OrderDraft.objects.get(pk=payload["id"])
        removed = next(item for item in payload["attachments"] if item["name"] == "a.png")
        payload = self.client.post(reverse("draft_save"), {
            **self.complete_data(), "_draft_id": str(draft.pk), "_draft_revision": str(payload["revision"]),
            "_remove_intake_attachments": str(removed["id"])}).json()
        self.assertNotIn("a.png", [item["name"] for item in payload["attachments"]])

    def test_wizard_renders_attachment_cards_with_delete_and_replace(self):
        payload = self.client.post(reverse("draft_save"), {**self.complete_data(), "supplement_documents": self.image("補充.png")}).json()
        response = self.client.get(reverse("order_create"), {"draft": payload["id"], "step": "deposit"}, follow=True)
        page = response.content.decode()
        for name in ("owner_bankbook", "installment_document", "supplement_documents"):
            self.assertRegex(page, rf'<input type="file" name="{name}"[^>]*data-intake-upload-input')
        self.assertIn('data-intake-attachment=', page)
        self.assertIn("data-intake-delete", page)
        self.assertIn("data-intake-replace", page)
        self.assertIn("js/intake-upload.js", page)
        self.assertNotIn("移除此附件", page)


class ReplacePreviewAndSubsidyUploadTests(inplace.InplaceUploadTests.__bases__[0]):
    setUpClass = inplace.InplaceUploadTests.setUpClass
    tearDownClass = inplace.InplaceUploadTests.tearDownClass
    setUp = inplace.InplaceUploadTests.setUp
    detail = inplace.InplaceUploadTests.detail

    def test_preview_url_changes_with_file(self):
        script = Path("static/js/document-previews.js").read_text(encoding="utf-8")
        self.assertIn("url.searchParams.set('v', link.dataset.previewName)", script)

    def test_subsidy_documents_uploadable_without_trade_in(self):
        SalesOrder.objects.filter(pk=self.order.pk).update(is_trade_in_subsidy=False)
        html = self.detail()
        row = html.split("<strong>新車主存摺封面</strong>", 1)[1].split("</article>", 1)[0]
        self.assertIn('value="new_owner_bankbook"', row)
        self.assertNotRegex(row, r"data-subsidy-upload-control\s+hidden")
        response = self.client.post(reverse("subsidy_document_upload", args=[self.order.pk]),
                                    {"document_type": "new_owner_bankbook", "file": png("bank.png")},
                                    HTTP_X_REQUESTED_WITH="XMLHttpRequest", HTTP_ACCEPT="application/json")
        self.assertTrue(response.json()["ok"])
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_trade_in_subsidy, "上傳不改變汰舊流程")
        self.assertTrue(SubsidyDocument.objects.filter(order=self.order, document_type="new_owner_bankbook").exists())
