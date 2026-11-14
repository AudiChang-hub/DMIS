import base64
from decimal import Decimal
from io import BytesIO

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from PIL import Image, ImageDraw
from pypdf import PdfReader

from sales.models import AccessoryLine, SalesOrder, SignatureMethod
from sales.services.document_signing import decode_signature
from sales.tests import test_order_flow as flow


def signature_data_url(blank=False, mode="RGBA", color=(20, 20, 20, 255)):
    image = Image.new(mode, (600, 200), (0, 0, 0, 0) if mode == "RGBA" else "white")
    if not blank:
        draw = ImageDraw.Draw(image)
        draw.line([(40, 150), (200, 40), (360, 160), (560, 60)], fill=color, width=6)
    output = BytesIO()
    image.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def pdf_text(content):
    return "".join(page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages)


class SignatureDecodeTests(TestCase):
    def test_rejects_blank_and_non_png(self):
        for value in ("", "data:image/jpeg;base64,AAAA", "data:image/png;base64,@@@", signature_data_url(blank=True)):
            with self.subTest(value=value[:30]):
                with self.assertRaises(ValidationError):
                    decode_signature(value)

    def test_crops_and_turns_light_ink_black(self):
        png = decode_signature(signature_data_url(color=(240, 240, 240, 255)))
        image = Image.open(BytesIO(png)).convert("RGBA")
        self.assertLess(image.width, 600)
        self.assertLess(image.height, 200)
        opaque = [pixel for pixel in image.getdata() if pixel[3] > 200]
        self.assertTrue(opaque)
        self.assertTrue(all(pixel[:3] == (0, 0, 0) for pixel in opaque))


class DocumentSigningTests(TestCase):
    setUp = flow.OrderFlowTests.setUp
    make_order = flow.OrderFlowTests.make_order

    def reprice(self, order, price):
        order = SalesOrder.objects.get(pk=order.pk)
        order.vehicle_price = Decimal(price)
        order.actual_balance = order.calculate_balance()
        order.save()
        return SalesOrder.objects.get(pk=order.pk)

    def sign(self, order, documents=("contract", "privacy"), **overrides):
        order = SalesOrder.objects.get(pk=order.pk)
        data = {
            "documents": list(documents),
            "signer_name": "王小明",
            "agree": "1",
            "signature": signature_data_url(),
            "fingerprint_contract": order.document_fingerprint("contract"),
            "fingerprint_privacy": order.document_fingerprint("privacy"),
        }
        data.update(overrides)
        return self.client.post(reverse("order_sign", args=[order.pk]), data)

    def test_sign_page_shows_document_previews(self):
        order = self.make_order()
        self.client.force_login(self.user)
        response = self.client.get(reverse("order_sign", args=[order.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data:image/png;base64,", count=2)
        self.assertContains(response, 'name="fingerprint_contract"')
        self.assertEqual(response["Cache-Control"], "private, no-store, max-age=0")

    def test_signing_stores_signed_pdfs_and_audit_events(self):
        order = self.make_order()
        self.client.force_login(self.user)
        response = self.sign(order)
        self.assertRedirects(response, reverse("order_sign_done", args=[order.pk]))
        order.refresh_from_db()
        self.assertTrue(order.signed_contract_is_electronic)
        self.assertTrue(order.privacy_consent_is_electronic)
        self.assertEqual(order.signed_contract_method, SignatureMethod.ELECTRONIC)
        with order.signed_contract.open("rb") as handle:
            contract = handle.read()
        self.assertEqual(len(PdfReader(BytesIO(contract)).pages), 2)
        self.assertIn("電子簽署", pdf_text(contract))
        self.assertIn("簽署人 王小明", pdf_text(contract))
        events = order.events.filter(event_type__endswith="_esigned")
        self.assertEqual(events.count(), 2)
        self.assertIn("SHA-256", events.first().description)
        done = self.client.get(reverse("order_sign_done", args=[order.pk]))
        self.assertContains(done, "車輛訂購單：已電子簽署")
        self.assertContains(done, "客人需要紙本副本嗎？")
        self.assertContains(done, "完成，返回訂單")
        self.assertContains(done, "列印含簽名的副本")
        self.assertContains(done, 'value="contract_store">')
        self.assertContains(done, 'value="contract_customer" checked>')

    def test_contract_change_keeps_signed_documents_valid(self):
        # 2026-10-15：訂購單實務上不會讓客人重簽，改內容不再判定失效。
        order = self.make_order()
        self.client.force_login(self.user)
        self.sign(order)
        order = SalesOrder.objects.get(pk=order.pk)
        order.final_plate_number = "ABC-1234"
        order.save()
        order = SalesOrder.objects.get(pk=order.pk)
        self.assertTrue(order.has_signed_contract)
        self.assertTrue(order.has_privacy_consent)

        order = self.reprice(order, "81800")
        self.assertFalse(order.signed_contract_stale)
        self.assertTrue(order.has_signed_contract)
        self.assertTrue(order.has_privacy_consent)
        detail = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "documents"})
        self.assertNotContains(detail, "需重簽")
        # 個資同意書仍有效電子簽署，訂單頁照樣可以印含簽名的副本。
        self.assertContains(detail, "選擇副本聯別")

    def test_accessory_and_owner_changes_do_not_invalidate_documents(self):
        order = self.make_order()
        self.client.force_login(self.user)
        self.sign(order)
        AccessoryLine.objects.create(order=order, name="後箱", amount=Decimal("1200"))
        order = SalesOrder.objects.get(pk=order.pk)
        self.assertFalse(order.signed_contract_stale)
        self.assertTrue(order.has_privacy_consent)
        order.owner_name = "王大明"
        order.actual_balance = order.calculate_balance()
        order.save()
        order = SalesOrder.objects.get(pk=order.pk)
        self.assertFalse(order.privacy_consent_stale)
        self.assertTrue(order.has_privacy_consent)

    def test_signing_is_rejected_when_content_changed_after_review(self):
        order = self.make_order()
        self.client.force_login(self.user)
        response = self.sign(order, fingerprint_contract="old")
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "內容剛被修改", status_code=400)
        order.refresh_from_db()
        self.assertFalse(order.signed_contract)

    def test_signing_requires_consent_and_signature(self):
        order = self.make_order()
        self.client.force_login(self.user)
        response = self.sign(order, agree="", signature=signature_data_url(blank=True))
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "同意以電子方式簽署", status_code=400)
        response = self.sign(order, signature=signature_data_url(blank=True))
        self.assertContains(response, "簽名太短或空白", status_code=400)

    def test_paper_upload_stays_valid_after_contract_change(self):
        order = self.make_order()
        self.client.force_login(self.user)
        self.client.post(
            reverse("contract_upload", args=[order.pk]),
            {"signed_contract": flow.uploaded_test_pdf("signed-contract.pdf")},
        )
        order = SalesOrder.objects.get(pk=order.pk)
        self.assertEqual(order.signed_contract_method, SignatureMethod.PAPER)
        self.assertTrue(order.has_signed_contract)
        order = self.reprice(order, "70000")
        self.assertTrue(order.has_signed_contract)

    def test_legacy_attachment_without_fingerprint_stays_valid(self):
        order = self.make_order(signed=True)
        order = self.reprice(order, "70000")
        self.assertTrue(order.has_signed_contract)

    def test_print_picker_selects_parts_and_uses_signed_copy(self):
        order = self.make_order()
        self.client.force_login(self.user)
        url = reverse("order_documents_print", args=[order.pk])
        everything = self.client.get(url)
        self.assertEqual(len(PdfReader(BytesIO(b"".join(everything.streaming_content))).pages), 3)

        self.sign(order, documents=("contract",))
        response = self.client.get(url, {"part": ["contract_customer", "privacy"]})
        content = b"".join(response.streaming_content)
        reader = PdfReader(BytesIO(content))
        self.assertEqual(len(reader.pages), 2)
        self.assertIn("客戶留存聯", reader.pages[0].extract_text())
        self.assertIn("電子簽署", reader.pages[0].extract_text())
        self.assertNotIn("電子簽署", reader.pages[1].extract_text())

    def test_many_accessories_continue_on_next_page_with_signature_last(self):
        # 配件多時明細續頁，確認事項與簽名移到該聯最後一頁，不再被明細壓住（使用者 2026-10-17）。
        order = self.make_order()
        AccessoryLine.objects.bulk_create(
            AccessoryLine(order=order, name=f"多買配件{index:02d}", amount=Decimal("500")) for index in range(40)
        )
        order = self.reprice(order, order.vehicle_price)
        self.client.force_login(self.user)
        sign_page = self.client.get(reverse("order_sign", args=[order.pk]))
        # 訂購單第一聯兩頁都給客人看，加上個資同意書一頁。
        self.assertContains(sign_page, "data:image/png;base64,", count=3)
        self.assertContains(sign_page, "內容預覽（第 2 頁）")

        self.sign(order, documents=("contract",))
        order.refresh_from_db()
        with order.signed_contract.open("rb") as handle:
            texts = [page.extract_text() for page in PdfReader(BytesIO(handle.read())).pages]
        self.assertEqual(len(texts), 4)
        for index, text in enumerate(texts):
            with self.subTest(page=index + 1):
                self.assertIn(f"頁次：{index + 1} / 4", text)
                self.assertIn("客戶留存聯" if index >= 2 else "店家留存聯", text)
                last_of_copy = index in (1, 3)
                self.assertEqual("客戶簽名" in text, last_of_copy)
                self.assertEqual("確認事項" in text, last_of_copy)
                self.assertEqual("電子簽署" in text, last_of_copy)
        self.assertIn("車 輛 訂 購 單（續）", texts[1])
        self.assertIn("多買配件39", texts[1])

        response = self.client.get(reverse("order_documents_print", args=[order.pk]), {"part": ["contract_customer"]})
        customer = [page.extract_text() for page in PdfReader(BytesIO(b"".join(response.streaming_content))).pages]
        self.assertEqual(len(customer), 2)
        self.assertTrue(all("客戶留存聯" in text for text in customer))

    def test_created_dialog_lets_staff_choose_device_or_paper_signing(self):
        order = self.make_order()
        self.client.force_login(self.user)
        detail = self.client.get(reverse("order_detail", args=[order.pk]), {"created": "1"})
        dialog = detail.content.decode().split('id="print-contract-dialog"', 1)[1].split("</dialog>", 1)[0]
        self.assertIn("這次要怎麼簽？", dialog)
        self.assertIn(reverse("order_sign", args=[order.pk]), dialog)
        self.assertIn("印出紙本給客人簽", dialog)
        self.assertIn('value="contract_store" checked>', dialog)
        self.assertIn('value="privacy" checked>', dialog)
        self.assertNotIn("選擇副本聯別", dialog)


class TaxConsentSigningTests(TestCase):
    """T-174（使用者 2026-11-13 選 A）：欣鈴退稅同意書比照個資同意書，可電子簽署或上傳紙本；
    只對 SUZUKI 油車＋汰舊出現，步驟完成判斷仍只看訂購單與個資同意書。"""

    setUp = flow.OrderFlowTests.setUp
    make_order = flow.OrderFlowTests.make_order
    sign = DocumentSigningTests.sign

    def eligible(self):
        self.model.brand = "SUZUKI"
        self.model.save()
        order = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(is_trade_in_subsidy=True)
        return SalesOrder.objects.get(pk=order.pk)

    def sign_tax(self, order, documents=("tax_consent",)):
        order = SalesOrder.objects.get(pk=order.pk)
        return self.sign(order, documents, fingerprint_tax_consent=order.document_fingerprint("tax_consent"))

    def test_sign_page_offers_tax_consent_only_when_applicable(self):
        self.client.force_login(self.user)
        plain = self.make_order()
        page = self.client.get(reverse("order_sign", args=[plain.pk]))
        self.assertNotContains(page, 'value="tax_consent"')
        self.assertNotContains(page, "欣鈴申請退稅同意書")
        order = self.eligible()
        page = self.client.get(reverse("order_sign", args=[order.pk]))
        self.assertContains(page, 'value="tax_consent" checked')
        self.assertContains(page, 'name="fingerprint_tax_consent"')
        self.assertContains(page, "data:image/png;base64,", count=3)
        self.assertContains(page, "銀行／郵局帳號欄留白")
        # 不適用的訂單即使送出 tax_consent 也不會簽。
        self.sign(plain, ("privacy", "tax_consent"))
        plain.refresh_from_db()
        self.assertFalse(plain.tax_consent)
        self.assertTrue(plain.privacy_consent_is_electronic)

    def test_signing_stores_tax_consent_without_account_and_keeps_step_rules(self):
        from sales.models import OrderOperationsProfile
        from sales.services.order_next_actions import build_order_next_actions
        from sales.services.order_steps import build_order_steps
        order = self.eligible()
        OrderOperationsProfile.objects.update_or_create(
            order=order, defaults={"bank_name": "測試銀行", "remittance_account": "012-3456789"},
        )
        self.client.force_login(self.user)
        response = self.sign_tax(order)
        self.assertRedirects(response, reverse("order_sign_done", args=[order.pk]))
        order.refresh_from_db()
        self.assertTrue(order.tax_consent_is_electronic)
        self.assertEqual(order.tax_consent_fingerprint, order.document_fingerprint("tax_consent"))
        with order.tax_consent.open("rb") as handle:
            signed = handle.read()
        text = pdf_text(signed)
        self.assertIn("申請退稅同意書", text)
        self.assertIn("簽署人 王小明", text)
        self.assertNotIn("012-3456789", text)
        self.assertEqual(order.events.filter(event_type="tax_consent_esigned").count(), 1)
        self.assertFalse(order.events.filter(event_type="payout_account_viewed").exists())
        done = self.client.get(reverse("order_sign_done", args=[order.pk]))
        self.assertContains(done, "欣鈴退稅同意書：已電子簽署")
        # 只簽退稅同意書：步驟 3 仍是選用，補簽提醒照舊列訂購單與個資同意書。
        steps = build_order_steps(order)["steps"]
        self.assertEqual(steps["documents"]["state"], "optional")
        self.assertIn("退稅同意書已電子簽署", steps["documents"]["summary"])
        actions = build_order_next_actions(order)
        archive = next(action for action in [actions.primary, *actions.secondary] if action and action.key == "documents")
        self.assertNotIn("退稅", archive.description)
        # 簽好訂購單與個資同意書即完成，不等退稅同意書。
        other = self.eligible()
        self.sign(other)
        other = SalesOrder.objects.get(pk=other.pk)
        self.assertFalse(other.tax_consent)
        self.assertEqual(build_order_steps(other)["steps"]["documents"]["state"], "done")

    def test_print_uses_signed_tax_consent(self):
        order = self.eligible()
        self.client.force_login(self.user)
        self.sign_tax(order)
        response = self.client.post(reverse("order_documents_print", args=[order.pk]), {"part": ["tax_consent"]})
        self.assertEqual(response.status_code, 200)
        text = pdf_text(b"".join(response.streaming_content))
        self.assertIn("簽署人 王小明", text)
        self.assertFalse(order.events.filter(event_type="payout_account_viewed").exists())

    def test_paper_upload_view_and_delete(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        order = self.eligible()
        self.client.force_login(self.user)
        detail = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "documents"})
        self.assertContains(detail, reverse("tax_consent_upload", args=[order.pk]))
        self.assertContains(detail, "尚未簽署")
        upload = SimpleUploadedFile("tax.pdf", b"%PDF-1.4 tax consent", content_type="application/pdf")
        self.client.post(reverse("tax_consent_upload", args=[order.pk]), {"tax_consent": upload})
        order.refresh_from_db()
        self.assertTrue(order.has_tax_consent)
        self.assertEqual(order.tax_consent_method, SignatureMethod.PAPER)
        self.assertIsNotNone(order.tax_consent_uploaded_at)
        self.assertEqual(order.signed_document_status, "1／3 已簽署")
        self.assertEqual(self.client.get(reverse("protected_media", args=["order", order.pk, "tax_consent"])).status_code, 200)
        detail = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "documents"})
        self.assertContains(detail, "1／3 已簽署")
        self.assertContains(detail, reverse("order_file_delete", args=[order.pk, "tax_consent"]))
        self.client.post(reverse("order_file_delete", args=[order.pk, "tax_consent"]))
        order.refresh_from_db()
        self.assertFalse(order.tax_consent)
        self.assertEqual((order.tax_consent_method, order.tax_consent_fingerprint, order.tax_consent_uploaded_at), ("", "", None))
        self.assertTrue(order.events.filter(event_type="tax_consent_deleted").exists())

    def test_orders_without_tax_consent_are_unchanged(self):
        order = self.make_order()
        self.client.force_login(self.user)
        upload = self.client.post(reverse("tax_consent_upload", args=[order.pk]), {})
        self.assertEqual(upload.status_code, 404)
        detail = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "documents"})
        self.assertNotContains(detail, reverse("tax_consent_upload", args=[order.pk]))
        self.assertContains(detail, "尚未簽署")
        self.assertEqual(order.signed_document_status, "尚未簽署")
        self.sign(order, ("privacy",))
        order = SalesOrder.objects.get(pk=order.pk)
        self.assertEqual(order.signed_document_status, "1／2 已簽署")
