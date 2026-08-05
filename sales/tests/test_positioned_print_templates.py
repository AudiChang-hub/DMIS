from io import BytesIO
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook
from pypdf import PdfReader

from sales.models import (
    PositionedPrintField,
    PositionedPrintTemplate,
    SalesOrder,
    VehicleColor,
    VehicleModel,
)
from sales.services.positioned_template_pdf import build_positioned_template_pdf


class PositionedPrintTemplateTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.media_override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.addCleanup(self.media_dir.cleanup)
        self.user = get_user_model().objects.create_user(
            username="template-tester", password="test-pass-123"
        )
        model = VehicleModel.objects.create(
            brand="SUZUKI", name="SUI 125", model_number="UQ125", energy_type="gas"
        )
        color = VehicleColor.objects.create(vehicle_model=model, name="灰")
        self.order = SalesOrder.objects.create(
            owner_type=SalesOrder.OwnerType.COMPANY,
            owner_name="列印測試有限公司",
            owner_phone="0912345678",
            owner_address="新北市汐止區",
            owner_id_number="83739807",
            vehicle_model=model,
            color=color,
            id_verified=True,
        )
        self.client.force_login(self.user)

    def _template(self, background=False):
        template = PositionedPrintTemplate.objects.create(
            name="測試報件單",
            document_type=PositionedPrintTemplate.DocumentType.SUBMISSION,
            version=1,
        )
        if background:
            workbook = Workbook()
            sheet = workbook.active
            sheet["A1"] = "固定標題"
            sheet["A2"] = "車主資料"
            stream = BytesIO()
            workbook.save(stream)
            template.background_file.save("submission.xlsx", ContentFile(stream.getvalue()))
        PositionedPrintField.objects.create(
            template=template,
            field_key="owner_name",
            label="車主",
            x_mm=20,
            y_mm=30,
            width_mm=80,
            font_size=12,
        )
        return template

    def test_blank_background_template_builds_pdf_with_order_value(self):
        output = build_positioned_template_pdf(self._template(), self.order)

        reader = PdfReader(output)
        self.assertEqual(len(reader.pages), 1)
        self.assertIn("列印測試有限公司", reader.pages[0].extract_text())

    def test_excel_visible_cells_are_used_as_background(self):
        output = build_positioned_template_pdf(self._template(background=True), self.order)

        text = PdfReader(output).pages[0].extract_text()
        self.assertIn("固定標題", text)
        self.assertIn("列印測試有限公司", text)

    def test_maintenance_and_order_print_routes(self):
        template = self._template()

        listing = self.client.get(reverse("positioned_template_list"))
        output = self.client.get(
            reverse("positioned_template_order_print", args=[template.pk, self.order.pk])
        )

        self.assertContains(listing, "測試報件單")
        self.assertEqual(output.status_code, 200)
        self.assertEqual(output["Content-Type"], "application/pdf")
