"""直接列印信封（T-173，使用者 11/13 選 A）：21×17 cm PDF 在新分頁開啟、用瀏覽器列印；Word 檔下載保留。"""
from decimal import Decimal
from io import BytesIO

from django.test import TestCase
from django.urls import reverse
from pypdf import PdfReader

from sales.models import OrderEvent, OrderOperationsProfile, SalesOrder, VehicleModel
from sales.services import form_print_preview
from sales.services.secret_fields import encrypt_secret
from sales.tests import test_order_lifecycle as lifecycle


def texts(content):
    """PDF 文字（逐字繪製，擷取時會插入換行；比對前去掉空白）。"""
    return ["".join((page.extract_text() or "").split()) for page in PdfReader(BytesIO(content)).pages]


class EnvelopeDirectPrintTests(TestCase):
    make_order = lifecycle.OrderLifecycleTests.make_order

    def setUp(self):
        lifecycle.OrderLifecycleTests.setUp(self)
        self.order, _vehicle = self.make_order(deposit=Decimal("5000"))
        self.other, _vehicle = self.make_order(deposit=Decimal("5000"))
        self.client.force_login(self.user)

    def post(self, jobs):
        return self.client.post(reverse("form_print_envelope_pdf"), {"job": jobs})

    def test_one_21_by_17_landscape_page_per_envelope(self):
        response = self.post([f"{self.order.pk}:envelope", f"{self.other.pk}:envelope", f"{self.order.pk}:receipt"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response["Content-Disposition"].startswith("inline;"))
        self.assertIn("no-store", response["Cache-Control"])
        pages = PdfReader(BytesIO(b"".join(response.streaming_content))).pages
        self.assertEqual(len(pages), 2)
        for page in pages:
            size = (round(float(page.mediabox.width) / 72 * 25.4), round(float(page.mediabox.height) / 72 * 25.4))
            self.assertEqual(size, (210, 170))
        first = "".join(pages[0].extract_text().split())
        self.assertIn("王小明", first)
        self.assertIn("車型：UQ125DA", first)

    def test_same_layout_as_preview_for_gas_envelopes(self):
        orders = list(SalesOrder.objects.select_related("vehicle_model", "source").filter(pk__in=[self.order.pk, self.other.pk]).order_by("pk"))
        self.assertEqual(texts(form_print_preview.build_envelope_print_pdf(orders)),
                         texts(form_print_preview.build_envelope_preview_pdf(orders)))

    def test_electric_password_is_printed_and_logged(self):
        VehicleModel.objects.filter(pk=self.model.pk).update(energy_type=VehicleModel.EnergyType.ELECTRIC)
        OrderOperationsProfile.objects.update_or_create(order=self.order, defaults={
            "vehicle_control_account": "bed768", "vehicle_control_password_encrypted": encrypt_secret("Pw-9527"),
        })
        response = self.post([f"{self.order.pk}:envelope"])
        self.assertIn("車控密碼：Pw-9527", texts(b"".join(response.streaming_content))[0])
        events = OrderEvent.objects.filter(order=self.order, event_type="secret_viewed")
        self.assertEqual(events.count(), 1)
        self.assertIn("直接列印電車信封", events.get().description)

    def test_get_is_not_allowed_and_nothing_picked_goes_back(self):
        self.assertEqual(self.client.get(reverse("form_print_envelope_pdf")).status_code, 405)
        self.assertEqual(self.post([f"{self.order.pk}:receipt"]).status_code, 302)

    def test_page_offers_button_with_printing_prerequisites(self):
        html = self.client.get(reverse("form_print")).content.decode()
        self.assertIn(f'formaction="{reverse("form_print_envelope_pdf")}" formtarget="_blank" data-submit-envelope-pdf', html)
        self.assertIn("下載信封 Word 檔", html)
        for text in ("21×17 公分", "自訂紙張", "實際大小", "第一次請先試印一張"):
            with self.subTest(text=text):
                self.assertIn(text, html)
        self.assertIn("data-preview-envelope-pdf", html)
