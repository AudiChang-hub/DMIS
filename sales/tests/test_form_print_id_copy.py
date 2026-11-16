"""T-190（2.13.0）：套表「身分證影本（實際尺寸）」與預覽點證件調整（合成證件圖，不含真實證件）。"""
import json
import re
import shutil
import tempfile
from decimal import Decimal

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from django.conf import settings
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from sales.models import OrderEvent, SalesOrder
from sales.services import form_print, id_card_crop
from sales.tests import id_card_synthetic as synthetic
from sales.tests import test_order_lifecycle as lifecycle

MM = 72 / 25.4
SCENE_SIZE = (1600, 1200)


def photo(side, **kwargs):
    return ContentFile(synthetic.jpeg_bytes(synthetic.scene(side, **kwargs)), name=f"{side}.jpg")


def image_boxes(pdf_bytes, page_index=0):
    """PDF 頁面上每張圖片的位置（mm，原點左下）。"""
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page = document[page_index]
        boxes = [obj.get_bounds() for obj in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE])]
        return sorted((left / MM, bottom / MM, right / MM, top / MM) for left, bottom, right, top in boxes), len(document)
    finally:
        document.close()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="t190-idcopy-"))
class IdCopyFormTests(TestCase):
    make_order = lifecycle.OrderLifecycleTests.make_order

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        lifecycle.OrderLifecycleTests.setUp(self)
        self.order, _vehicle = self.make_order(deposit=Decimal("5000"))
        self.order.id_front = photo("front")
        self.order.id_back = photo("back", upside_down=True)
        self.order.save(update_fields=["id_front", "id_back"])
        self.client.force_login(self.user)

    def job(self, order=None):
        return form_print.PrintJob(order or self.order, "id_copy")

    def test_form_is_listed_and_applies_to_people_with_photos(self):
        self.assertIn("id_copy", form_print.FORM_KEYS)
        self.assertEqual(form_print.FORM_BY_KEY["id_copy"].label, "身分證影本（實際尺寸）")
        self.assertTrue(form_print.id_copy_applies(self.order))
        self.order.owner_type = SalesOrder.OwnerType.FOREIGN
        self.assertTrue(form_print.id_copy_applies(self.order))
        self.assertEqual(form_print.id_copy_document_label(self.order), "居留證")
        self.order.owner_type = SalesOrder.OwnerType.COMPANY
        self.assertFalse(form_print.id_copy_applies(self.order))
        other, _vehicle = self.make_order()
        self.assertFalse(form_print.id_copy_applies(other))

        response = self.client.get(reverse("form_print"))
        self.assertContains(response, 'data-form="id_copy"')
        self.assertContains(response, "限自然人、需有證件照片")

    def test_cards_print_at_actual_size_side_by_side_one_page_per_order(self):
        pdf = form_print.build_forms_pdf([self.job()])
        boxes, pages = image_boxes(pdf)
        self.assertEqual(pages, 1)
        self.assertEqual(len(boxes), 2)
        for left, bottom, right, top in boxes:
            self.assertAlmostEqual(right - left, 85.6, delta=0.1)
            self.assertAlmostEqual(top - bottom, 54.0, delta=0.1)
            self.assertAlmostEqual(297 - top, form_print.ID_CARD_TOP, delta=0.1)
        (front_left, *_), (back_left, *_) = boxes
        self.assertAlmostEqual(back_left - front_left, 85.6 + form_print.ID_CARD_GAP, delta=0.1)

    def test_saved_crop_is_used_and_missing_crop_is_detected_without_saving(self):
        params = id_card_crop.params_from_pixels(synthetic.TILTED, 0, SCENE_SIZE, "manual")
        self.order.id_front_crop = params
        self.order.save(update_fields=["id_front_crop"])
        job = self.job()
        form_print.build_forms_pdf([job])
        front, back = job.id_slots
        self.assertTrue(front["saved"])
        self.assertEqual(front["crop"], params)
        self.assertFalse(back["saved"])
        self.assertEqual(back["crop"]["turn"], 2)  # 反面倒著拍，自動轉正
        self.order.refresh_from_db()
        self.assertIsNone(self.order.id_back_crop)

    def test_missing_side_prints_placeholder(self):
        self.order.id_back = ""
        self.order.save(update_fields=["id_back"])
        boxes, _pages = image_boxes(form_print.build_forms_pdf([self.job()]))
        self.assertEqual(len(boxes), 1)

    def test_preview_has_hotspots_without_writing_and_print_logs_event(self):
        data = {"job": [f"{self.order.pk}:id_copy"]}
        response = self.client.post(reverse("form_print_preview"), data)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertEqual(content.count("data-id-copy-card"), 2)
        self.assertIn(f'data-src="{reverse("protected_media", args=["order", self.order.pk, "id_front"])}"', content)
        self.assertRegex(content, r'left: [0-9.]+%; top: 8\.081%; width: 40\.762%; height: 18\.182%')
        self.assertIn('data-saved="0"', content)
        self.assertFalse(OrderEvent.objects.filter(order=self.order, event_type="identity_copy_printed").exists())

        printed = b"".join(self.client.post(reverse("form_print_pdf"), data).streaming_content)
        self.assertTrue(printed.startswith(b"%PDF"))
        event = OrderEvent.objects.get(order=self.order, event_type="identity_copy_printed")
        self.assertIn("身分證影本", event.description)

    def test_adjusting_in_preview_saves_back_to_order(self):
        url = reverse("form_print_id_crop", args=[self.order.pk])
        revision = self.order.revision
        params = id_card_crop.params_from_pixels(synthetic.TILTED, 2, SCENE_SIZE, "manual")
        response = self.client.post(url, {"side": "back", "crop": json.dumps(params)})
        self.assertEqual(response.status_code, 200, response.content)
        self.order.refresh_from_db()
        self.assertEqual(self.order.id_back_crop, params)
        self.assertEqual(self.order.revision, revision + 1)
        self.assertEqual(OrderEvent.objects.filter(order=self.order, event_type="id_crop_adjusted").count(), 1)

        # 同樣的參數再存一次：不改版本、不重複記錄。
        self.client.post(url, {"side": "back", "crop": json.dumps(params)})
        self.order.refresh_from_db()
        self.assertEqual(self.order.revision, revision + 1)
        self.assertEqual(OrderEvent.objects.filter(order=self.order, event_type="id_crop_adjusted").count(), 1)

        # 下一次預覽用存回的參數。
        job = self.job(self.order)
        form_print.build_forms_pdf([job])
        self.assertTrue(job.id_slots[1]["saved"])

    def test_adjusting_rejects_bad_requests(self):
        url = reverse("form_print_id_crop", args=[self.order.pk])
        params = id_card_crop.params_from_pixels(synthetic.TILTED, 0, SCENE_SIZE, "manual")
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, {"side": "top", "crop": json.dumps(params)}).status_code, 400)
        wrong_size = id_card_crop.params_from_pixels(synthetic.TILTED, 0, (800, 600), "manual")
        self.assertEqual(self.client.post(url, {"side": "front", "crop": json.dumps(wrong_size)}).status_code, 400)
        self.assertEqual(self.client.post(url, {"side": "front", "crop": "nope"}).status_code, 400)
        other, _vehicle = self.make_order()
        self.assertEqual(self.client.post(reverse("form_print_id_crop", args=[other.pk]),
                                          {"side": "front", "crop": json.dumps(params)}).status_code, 400)
        self.order.refresh_from_db()
        self.assertIsNone(self.order.id_front_crop)

    def test_page_loads_crop_editor_scripts(self):
        response = self.client.get(reverse("form_print"))
        self.assertContains(response, "js/id-crop-editor.js")
        self.assertContains(response, "js/form-print-id-copy.js")
        self.assertContains(response, f'data-id-crop-save-url="{reverse("form_print_id_crop", args=[0])}"')
        self.assertTrue(re.search(r'data-paper="id_copy"', response.content.decode()))
