"""電車交車確認表（T-158，使用者 2026-11-13）：套表列印新增一份，只給 eReady、eMOVING 的電車。"""
from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image
from pypdf import PdfReader

from sales.models import SalesOrder, VehicleBrand, VehicleModel
from sales.services import form_print
from sales.tests import test_order_lifecycle as lifecycle


def png_bytes():
    output = BytesIO()
    Image.new("RGB", (120, 30), "navy").save(output, format="PNG")
    return output.getvalue()


class EvDeliveryFormTests(TestCase):
    make_order = lifecycle.OrderLifecycleTests.make_order

    def setUp(self):
        lifecycle.OrderLifecycleTests.setUp(self)
        self.gas, _vehicle = self.make_order(deposit=Decimal("5000"))
        self.eready = self.electric_order("eReady", "Fun", "EV060L")
        self.client.force_login(self.user)

    def electric_order(self, brand, name, number):
        order, _vehicle = self.make_order(deposit=Decimal("5000"))
        model = VehicleModel.objects.create(brand=brand, name=name, model_number=number,
                                            energy_type=VehicleModel.EnergyType.ELECTRIC)
        SalesOrder.objects.filter(pk=order.pk).update(
            vehicle_model=model, final_plate_number="TST-0002", owner_address="測試市測試路 1 號",
        )
        return SalesOrder.objects.select_related("vehicle_model", "color").get(pk=order.pk)

    def pdf(self, *jobs):
        return PdfReader(BytesIO(form_print.build_forms_pdf([form_print.PrintJob(order, "ev_delivery") for order in jobs])))

    def test_only_eready_and_emoving_electric_orders(self):
        self.assertTrue(form_print.ev_delivery_applies(self.eready))
        self.assertTrue(form_print.ev_delivery_applies(self.electric_order("eMOVING", "EZ1", "EM3H1")))
        self.assertFalse(form_print.ev_delivery_applies(self.electric_order("GOGORO", "VIVA", "GF2XT")))
        self.assertFalse(form_print.ev_delivery_applies(self.gas))

    def test_a4_page_carries_order_fields(self):
        page = self.pdf(self.eready).pages[0]
        size = (round(float(page.mediabox.width) / 72 * 25.4), round(float(page.mediabox.height) / 72 * 25.4))
        self.assertEqual(size, (210, 297))
        text = page.extract_text()
        for value in ("交車確認", "EV060L", "灰", "王小明", "0912345678", "TST-0002", "測試市測試路 1 號", "顧客簽名"):
            with self.subTest(value=value):
                self.assertIn(value, text)
        self.assertEqual(len(page.images), 1)  # eReady logo

    def test_emoving_uses_uploaded_brand_logo_or_leaves_blank(self):
        emoving = self.electric_order("eMOVING", "EZ1", "EM3H1")
        self.assertEqual(len(self.pdf(emoving).pages[0].images), 0)
        brand, _created = VehicleBrand.objects.get_or_create(name="eMOVING")
        brand.logo = SimpleUploadedFile("logo.png", png_bytes(), content_type="image/png")
        brand.save()
        self.assertEqual(len(self.pdf(emoving).pages[0].images), 1)

    def test_suggested_and_warnings(self):
        values = form_print.form_values(self.eready)
        self.assertIn("ev_delivery", form_print.suggested_forms(self.eready, values))
        self.assertEqual(form_print.form_warnings(self.eready, values)["ev_delivery"], [])
        SalesOrder.objects.filter(pk=self.eready.pk).update(final_plate_number="")
        order = SalesOrder.objects.get(pk=self.eready.pk)
        self.assertEqual(form_print.form_warnings(order, form_print.form_values(order))["ev_delivery"], ["車牌"])
        gas_values = form_print.form_values(self.gas)
        self.assertNotIn("ev_delivery", form_print.suggested_forms(self.gas, gas_values))
        self.assertEqual(form_print.suggested_forms(self.gas, gas_values), ["envelope", "receipt"])

    def test_print_page_offers_toggle_only_for_applicable_orders(self):
        response = self.client.get(reverse("form_print"))
        self.assertContains(response, 'data-form="ev_delivery"', count=1)
        self.assertContains(response, "電車交車確認表")
        self.assertContains(response, "不適用（限 eReady、eMOVING）", count=1)

    def test_pdf_and_preview_skip_orders_that_do_not_apply(self):
        response = self.client.post(reverse("form_print_pdf"), {
            "job": [f"{self.eready.pk}:ev_delivery", f"{self.gas.pk}:ev_delivery", f"{self.gas.pk}:receipt"],
        })
        self.assertEqual(response.status_code, 200)
        pages = PdfReader(BytesIO(b"".join(response.streaming_content))).pages
        self.assertEqual(len(pages), 2)
        self.assertIn("交車確認", pages[1].extract_text())
        self.assertNotIn("交車確認", pages[0].extract_text())

        only_gas = self.client.post(reverse("form_print_pdf"), {"job": [f"{self.gas.pk}:ev_delivery"]})
        self.assertEqual(only_gas.status_code, 302)

        preview = self.client.post(reverse("form_print_preview"), {"job": [f"{self.eready.pk}:ev_delivery"]})
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, "A4")
