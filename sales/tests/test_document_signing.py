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
        self.assertContains(done, "列印勾選的文件")
        self.assertContains(done, "不列印，返回訂單")

    def test_contract_change_requires_resigning_but_payment_progress_does_not(self):
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
        self.assertTrue(order.signed_contract_stale)
        self.assertFalse(order.has_signed_contract)
        self.assertTrue(order.has_privacy_consent)
        detail = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "documents"})
        self.assertContains(detail, "內容已變更，需重簽")

    def test_accessory_and_owner_changes_invalidate_documents(self):
        order = self.make_order()
        self.client.force_login(self.user)
        self.sign(order)
        AccessoryLine.objects.create(order=order, name="後箱", amount=Decimal("1200"))
        order = SalesOrder.objects.get(pk=order.pk)
        self.assertTrue(order.signed_contract_stale)
        self.assertTrue(order.has_privacy_consent)
        order.owner_name = "王大明"
        order.actual_balance = order.calculate_balance()
        order.save()
        order = SalesOrder.objects.get(pk=order.pk)
        self.assertTrue(order.privacy_consent_stale)

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

    def test_paper_upload_also_requires_resigning_after_contract_change(self):
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
        self.assertFalse(order.has_signed_contract)

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

    def test_created_dialog_offers_tablet_signing_and_print_choice(self):
        order = self.make_order()
        self.client.force_login(self.user)
        detail = self.client.get(reverse("order_detail", args=[order.pk]), {"created": "1"})
        self.assertContains(detail, reverse("order_sign", args=[order.pk]))
        self.assertContains(detail, "要列印哪幾份？")
        self.assertContains(detail, 'value="contract_customer"')
