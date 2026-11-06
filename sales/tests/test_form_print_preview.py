"""套表列印預覽（使用者 2026-11-06 T-118）：列印前先看帶入資料後的樣子；內容與實際輸出一致，只讀不寫。"""
import html
import re
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import pypdfium2 as pdfium
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from sales.models import OrderEvent, OrderOperationsProfile, SalesOrder, VehicleModel
from sales.services import form_print, form_print_preview
from sales.services.secret_fields import encrypt_secret
from sales.tests import test_order_lifecycle as lifecycle
from sales.tests.test_form_print import docx_document, docx_text
from sales.tests.test_get_requests_read_only import _written_tables

SAMPLE = {
    "dealer": "A12", "owner_name": "王小明", "model_number": "SWISH 125", "color": "消光黑", "identifier": "F4A1-123456",
    "plate": "ABC-1234", "vehicle_control_account": "0912345678", "vehicle_control_password": "pass1234",
    "installment_info": "和潤企業 36 期 每期 3,210 元 首期 2026/12/05", "customer_service_phone": "客服專線 0800-000-000",
}
# Word 2016 開啟同一份信封 Word 檔、另存 PDF 量到的每行起點與基線（mm，距紙張左上）。
WORD_OIL = [(29.43, 48.91), (51.95, 60.77), (51.95, 73.47), (51.95, 86.18), (51.95, 98.88), (29.22, 127.05), (29.22, 133.40)]
WORD_EV = [(31.90, 45.74), (51.95, 57.60), (51.95, 70.30), (51.95, 83.01), (51.95, 95.71), (51.95, 108.42), (51.95, 121.12),
           (32.18, 136.72), (32.18, 143.07)]


def _body(electric):
    body = form_print._envelope_body(SimpleNamespace(is_electric_vehicle=electric), SAMPLE)
    top, bottom = form_print._ENVELOPE_MARGINS[electric]
    return body + f'<w:sectPr><w:pgMar w:top="{top}" w:bottom="{bottom}"/></w:sectPr>'


def _pdf_text(pdf_bytes):
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        return ["".join(document[i].get_textpage().get_text_range().split()) for i in range(len(document))]
    finally:
        document.close()


class EnvelopeLayoutTests(TestCase):
    def test_lines_match_word_output_within_a_fifth_of_a_millimetre(self):
        for electric, expected in ((False, WORD_OIL), (True, WORD_EV)):
            placed = form_print_preview.envelope_layout(_body(electric))
            self.assertEqual(len(placed), len(expected))
            for (x, baseline, _runs), (word_x, word_baseline) in zip(placed, expected):
                self.assertAlmostEqual(x, word_x, delta=0.2)
                self.assertAlmostEqual(baseline, word_baseline, delta=0.2)

    def test_long_text_wraps_inside_the_cell(self):
        values = {**SAMPLE, "installment_info": "分期資料" * 40}
        body = form_print._envelope_body(SimpleNamespace(is_electric_vehicle=False), values)
        placed = form_print_preview.envelope_layout(body + '<w:sectPr><w:pgMar w:top="2268" w:bottom="1134"/></w:sectPr>')
        wrapped = [runs for _x, _b, runs in placed if runs[0][0].startswith("分期")]
        self.assertGreater(len(wrapped), 1)
        self.assertEqual("".join(text for runs in wrapped for text, _size in runs), "分期資料" * 40)


class FormPrintPreviewTests(TestCase):
    make_order = lifecycle.OrderLifecycleTests.make_order

    def setUp(self):
        lifecycle.OrderLifecycleTests.setUp(self)
        self.order, _vehicle = self.make_order(deposit=Decimal("5000"))
        self.other, _vehicle = self.make_order(dealer=True, deposit=Decimal("5000"))
        self.client.force_login(self.user)

    def preview(self, data):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.post(reverse("form_print_preview"), data)
        self.assertEqual(_written_tables(ctx.captured_queries), set(), "預覽不得寫入資料")
        return response

    def srcs(self, response):
        return re.findall(r'src="(data:image/webp;base64,[^"]+)"', response.content.decode())

    def test_page_offers_preview_for_whole_tray_and_each_order(self):
        response = self.client.get(reverse("form_print"))

        self.assertContains(response, "data-preview-open")
        self.assertContains(response, "data-preview-item")
        self.assertContains(response, "data-preview-dialog")
        self.assertContains(response, reverse("form_print_preview"))

    def test_a4_preview_is_the_printed_pdf(self):
        data = {
            "job": [f"{self.order.pk}:receipt", f"{self.other.pk}:tax_declaration", f"{self.order.pk}:tax_declaration"],
            f"note_{self.order.pk}": "■期望送達時間：週一",
            f"address_{self.order.pk}": "新北市三重區",
            "group": "form",
        }
        printed = b"".join(self.client.post(reverse("form_print_pdf"), data).streaming_content)

        response = self.preview(data)

        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        expected = [page["src"] for page in form_print_preview.render_pages(printed)]
        self.assertEqual(self.srcs(response), expected)
        # 依套表分組：聲明書兩張在前、簽收單在後，和列印順序相同。
        labels = re.findall(r"<strong>([^<]+)</strong><small>", response.content.decode())
        declaration = form_print.FORM_BY_KEY["tax_declaration"].label
        self.assertEqual(labels, [declaration, declaration, "簽收單"])

    def test_preview_follows_order_grouping(self):
        data = {"job": [f"{self.order.pk}:receipt", f"{self.other.pk}:tax_declaration"], "group": "order"}

        response = self.preview(data)

        labels = re.findall(r"<strong>([^<]+)</strong><small>", response.content.decode())
        self.assertEqual(labels, ["簽收單", form_print.FORM_BY_KEY["tax_declaration"].label])

    def test_envelope_preview_carries_the_word_file_text(self):
        jobs = [f"{self.order.pk}:envelope", f"{self.other.pk}:envelope"]
        word = docx_document(b"".join(self.client.post(reverse("form_print_envelopes"), {"job": jobs}).streaming_content))
        orders = list(SalesOrder.objects.select_related("vehicle_model", "source", "operations").filter(
            pk__in=[self.order.pk, self.other.pk]).order_by("pk"))

        preview_text = _pdf_text(form_print_preview.build_envelope_preview_pdf(orders))
        response = self.preview({"job": jobs})

        self.assertEqual(len(self.srcs(response)), 2)
        self.assertContains(response, "21 × 17 cm", count=2)
        # 每張訂單一頁，逐字（去掉空白）和 Word 檔相同。
        self.assertEqual(len(preview_text), 2)
        self.assertEqual("".join(preview_text), "".join(html.unescape(docx_text(word)).split()))

    def test_electric_password_is_not_decrypted_or_logged(self):
        VehicleModel.objects.filter(pk=self.model.pk).update(energy_type=VehicleModel.EnergyType.ELECTRIC)
        OrderOperationsProfile.objects.update_or_create(order=self.order, defaults={
            "vehicle_control_account": "bed768", "vehicle_control_password_encrypted": encrypt_secret("Pw-9527"),
        })
        order = SalesOrder.objects.select_related("vehicle_model", "source", "operations").get(pk=self.order.pk)

        response = self.preview({"job": [f"{self.order.pk}:envelope"]})
        text = "".join(_pdf_text(form_print_preview.build_envelope_preview_pdf([order])))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "車控密碼在預覽不顯示")
        self.assertNotIn("Pw-9527", text)
        self.assertIn("車控密碼：" + "".join(form_print_preview.PASSWORD_PLACEHOLDER.split()), text)
        self.assertFalse(OrderEvent.objects.filter(order=self.order, event_type="secret_viewed").exists())

    def test_large_batches_preview_first_pages_and_say_how_many_remain(self):
        with mock.patch.object(form_print_preview, "MAX_PAGES", 1):
            response = self.preview({"job": [f"{self.order.pk}:envelope", f"{self.other.pk}:envelope"]})

        self.assertEqual(len(self.srcs(response)), 1)
        self.assertContains(response, "另有 1 張不在預覽中，列印時都會包含。")

    def test_nothing_picked_or_out_of_scope_returns_message(self):
        response = self.preview({"job": []})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "請至少勾選一張訂單的一份套表。", status_code=400)

        SalesOrder.objects.filter(pk=self.other.pk).update(deleted_at="2026-10-14T00:00:00+08:00")
        response = self.preview({"job": [f"{self.other.pk}:receipt"]})
        self.assertContains(response, "勾選的訂單已不存在或沒有權限列印。", status_code=400)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(reverse("form_print_preview")).status_code, 405)
