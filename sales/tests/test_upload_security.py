from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from openpyxl import Workbook
from PIL import Image
from pypdf import PdfWriter

from sales.forms import (
    DeliveryCompletionForm,
    PaymentRecordForm,
    PrivacyConsentForm,
    RegistrationDocumentUploadForm,
    SignedContractForm,
)
from sales.models import RegistrationDocument, SalesOrder
from sales.services.upload_validation import (
    DOCUMENT_MAX_BYTES,
    IMAGE_MAX_BYTES,
    validate_document_upload,
    validate_excel_upload,
    validate_image_upload,
    validate_subsidy_upload,
    validate_template_background,
)


def uploaded_png(name="document.png"):
    stream = BytesIO()
    Image.new("RGB", (32, 24), "white").save(stream, format="PNG")
    return SimpleUploadedFile(name, stream.getvalue(), content_type="image/png")


def uploaded_pdf(name="document.pdf"):
    stream = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=200)
    writer.write(stream)
    return SimpleUploadedFile(name, stream.getvalue(), content_type="application/pdf")


def uploaded_xlsx(name="background.xlsx"):
    stream = BytesIO()
    workbook = Workbook()
    workbook.active["A1"] = "報件單"
    workbook.save(stream)
    return SimpleUploadedFile(
        name,
        stream.getvalue(),
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )


class UploadValidationTests(SimpleTestCase):
    def test_real_image_pdf_and_excel_are_accepted(self):
        self.assertIsNotNone(validate_image_upload(uploaded_png()))
        self.assertIsNotNone(validate_document_upload(uploaded_png()))
        self.assertIsNotNone(validate_document_upload(uploaded_pdf()))
        self.assertIsNotNone(validate_excel_upload(uploaded_xlsx()))
        self.assertIsNotNone(validate_template_background(uploaded_xlsx()))

    def test_html_renamed_as_pdf_is_rejected(self):
        upload = SimpleUploadedFile(
            "contract.pdf",
            b"<!doctype html><script>alert(1)</script>",
            content_type="application/pdf",
        )

        with self.assertRaisesMessage(Exception, "有效的 PDF"):
            validate_document_upload(upload)

    def test_pdf_with_active_javascript_is_rejected(self):
        stream = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=200)
        writer.add_js("app.alert('unsafe')")
        writer.write(stream)
        upload = SimpleUploadedFile(
            "active.pdf", stream.getvalue(), content_type="application/pdf"
        )

        with self.assertRaisesMessage(Exception, "腳本"):
            validate_document_upload(upload)

    def test_declared_html_mime_is_rejected_even_with_image_extension(self):
        upload = SimpleUploadedFile(
            "receipt.png",
            b"<html>not an image</html>",
            content_type="text/html",
        )

        with self.assertRaisesMessage(Exception, "檔案類型與副檔名不符"):
            validate_document_upload(upload)

    def test_corrupted_image_is_rejected(self):
        upload = SimpleUploadedFile(
            "receipt.jpg", b"\xff\xd8broken", content_type="image/jpeg"
        )

        with self.assertRaisesMessage(Exception, "圖片已損壞"):
            validate_document_upload(upload)

    def test_identity_image_and_legacy_excel_reject_disguised_files(self):
        disguised_image = SimpleUploadedFile(
            "identity.png", b"<html>fake</html>", content_type="image/png"
        )
        disguised_excel = SimpleUploadedFile(
            "history.xlsx",
            b"not a zip workbook",
            content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )

        with self.assertRaisesMessage(Exception, "圖片已損壞"):
            validate_image_upload(disguised_image)
        with self.assertRaisesMessage(Exception, "Office 檔案"):
            validate_excel_upload(disguised_excel)

    def test_oversized_document_is_rejected_before_parsing(self):
        upload = SimpleUploadedFile(
            "huge.pdf",
            b"%PDF-1.7\n" + b"0" * DOCUMENT_MAX_BYTES,
            content_type="application/pdf",
        )

        with self.assertRaisesMessage(Exception, "20 MB"):
            validate_document_upload(upload)

    def test_zip_without_excel_structure_is_rejected(self):
        stream = BytesIO()
        with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
            archive.writestr("harmless.txt", "not an excel workbook")
        upload = SimpleUploadedFile(
            "background.xlsx",
            stream.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )

        with self.assertRaisesMessage(Exception, "Office 檔案結構不完整"):
            validate_template_background(upload)

    def test_subsidy_keeps_csv_and_docx_formats(self):
        csv_upload = SimpleUploadedFile(
            "note.csv", "項目,金額\n地方政府,12000".encode(), content_type="text/csv"
        )
        self.assertIsNotNone(validate_subsidy_upload(csv_upload))

        stream = BytesIO()
        with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("_rels/.rels", "<Relationships/>")
            archive.writestr("word/document.xml", "<document/>")
        docx_upload = SimpleUploadedFile(
            "other.docx",
            stream.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
        )
        self.assertIsNotNone(validate_subsidy_upload(docx_upload))


class UploadFormIntegrationTests(SimpleTestCase):
    def test_contract_and_privacy_forms_apply_server_side_validation(self):
        contract = SignedContractForm(files={"signed_contract": uploaded_pdf()})
        privacy = PrivacyConsentForm(files={"privacy_consent": uploaded_png()})

        self.assertTrue(contract.is_valid(), contract.errors)
        self.assertTrue(privacy.is_valid(), privacy.errors)

    def test_registration_document_rejects_fake_pdf(self):
        fake_pdf = SimpleUploadedFile(
            "invoice.pdf", b"<html>fake</html>", content_type="application/pdf"
        )
        form = RegistrationDocumentUploadForm(
            data={
                "document_type": RegistrationDocument.DocumentType.INVOICE,
                "name": "",
            },
            files={"file": fake_pdf},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("有效的 PDF", form.errors["file"][0])

    def test_payment_proof_rejects_corrupted_image(self):
        form = PaymentRecordForm(
            data={
                "item_name": "尾款",
                "expected_amount": "1000",
                "received_amount": "1000",
                "card_principal": "0",
                "card_fee_charged": "0",
                "bank_card_fee": "0",
                "received_on": "2026-08-06",
                "payment_method": "匯款",
                "receiving_account": "公司帳戶",
                "confirmed": "",
                "note": "",
            },
            files={
                "proof": SimpleUploadedFile(
                    "proof.png", b"broken", content_type="image/png"
                )
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("圖片已損壞", form.errors["proof"][0])

    def test_delivery_photo_uses_the_image_security_validator(self):
        order = SalesOrder(owner_name="測試車主", owner_phone="0912345678")
        valid_png = uploaded_png("handover.png").read()
        form = DeliveryCompletionForm(
            order,
            data={
                "delivery_method": SalesOrder.DeliveryMethod.STORE_PICKUP,
                "delivery_destination": "",
                "delivered_at": "2026-08-06T12:00",
                "recipient_name": "測試車主",
                "recipient_phone": "0912345678",
                "carrier_name": "",
                "handover_location": "馭盛國際有限公司",
                "vehicle_condition_note": DeliveryCompletionForm.VEHICLE_CONDITION_NORMAL,
                "condition_checked": "on",
                "documents_checked": "on",
                "keys_checked": "on",
                "accessories_checked": "on",
                "payment_checked": "on",
                "note": "",
            },
            files={
                "handover_photo": SimpleUploadedFile(
                    "handover.png",
                    valid_png + b"0" * (IMAGE_MAX_BYTES - len(valid_png) + 1),
                    content_type="image/png",
                )
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("12 MB", form.errors["handover_photo"][0])
