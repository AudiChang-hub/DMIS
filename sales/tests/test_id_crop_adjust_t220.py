"""T-220：證件裁切加亮度（-50～+50）、清晰度（0～100），照身分證排版工具；存在既有裁切參數裡，PDF 與卡片圖都套用。"""
import json
import shutil
import tempfile
from decimal import Decimal
from io import BytesIO

import numpy as np
from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from sales.models import OrderEvent
from sales.services import form_print, id_card_crop
from sales.tests import id_card_synthetic as synthetic
from sales.tests import test_order_lifecycle as lifecycle
from sales.tests.test_form_print_id_copy import SCENE_SIZE, photo

BASE = id_card_crop.params_from_pixels(synthetic.TILTED, 0, SCENE_SIZE, "manual")


class AdjustParamsTests(SimpleTestCase):
    def test_brightness_and_sharpness_are_kept_clamped_and_zero_dropped(self):
        cleaned = id_card_crop.clean_params({**BASE, "brightness": 20, "sharpness": 35}, SCENE_SIZE)
        self.assertEqual((cleaned["brightness"], cleaned["sharpness"]), (20, 35))
        cleaned = id_card_crop.clean_params({**BASE, "brightness": -999, "sharpness": 999}, SCENE_SIZE)
        self.assertEqual((cleaned["brightness"], cleaned["sharpness"]), (-50, 100))
        cleaned = id_card_crop.clean_params({**BASE, "brightness": 0, "sharpness": -5}, SCENE_SIZE)
        self.assertNotIn("brightness", cleaned)
        self.assertNotIn("sharpness", cleaned, "0 不存，舊參數格式不變")
        for bad in ("abc", None, [], float("nan"), float("inf")):
            cleaned = id_card_crop.clean_params({**BASE, "brightness": bad}, SCENE_SIZE)
            self.assertIsNotNone(cleaned, "亮度格式錯誤不讓整份裁切失效")
            self.assertNotIn("brightness", cleaned)

    def test_old_params_are_unchanged(self):
        self.assertEqual(id_card_crop.clean_params(BASE, SCENE_SIZE), BASE)

    def test_brightness_table_matches_the_tool(self):
        self.assertEqual([int(id_card_crop.brightness_table(50)[i]) for i in (0, 128, 255)], [0, 172, 255])
        self.assertEqual([int(id_card_crop.brightness_table(-50)[i]) for i in (0, 128, 255)], [0, 77, 255])
        self.assertEqual(list(id_card_crop.brightness_table(0)), list(range(256)))

    def test_apply_crop_brightens_and_sharpens_only_when_asked(self):
        image = synthetic.to_pil(synthetic.scene("front"))
        plain = np.asarray(id_card_crop.apply_crop(image, BASE), dtype=np.int16)
        warped = id_card_crop.warp(np.asarray(image), id_card_crop.pixel_corners(BASE), 0)
        self.assertTrue(np.array_equal(plain, warped), "沒調整時輸出和改版前一樣")
        brighter = np.asarray(id_card_crop.apply_crop(image, {**BASE, "brightness": 40}), dtype=np.int16)
        darker = np.asarray(id_card_crop.apply_crop(image, {**BASE, "brightness": -40}), dtype=np.int16)
        self.assertGreater(brighter.mean(), plain.mean() + 10)
        self.assertLess(darker.mean(), plain.mean() - 10)
        sharp = np.asarray(id_card_crop.apply_crop(image, {**BASE, "sharpness": 100}), dtype=np.int16)
        edges = lambda array: np.abs(np.diff(array.mean(axis=2), axis=1)).mean()  # noqa: E731
        self.assertGreater(edges(sharp), edges(plain) * 1.2, "清晰度加強邊緣")
        self.assertEqual(sharp.shape, plain.shape)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="t217-adjust-"))
class AdjustSavedAndPrintedTests(TestCase):
    make_order = lifecycle.OrderLifecycleTests.make_order

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        lifecycle.OrderLifecycleTests.setUp(self)
        self.order, _vehicle = self.make_order(deposit=Decimal("5000"))
        self.order.id_front = photo("front")
        self.order.id_back = photo("back")
        self.order.save(update_fields=["id_front", "id_back"])
        self.client.force_login(self.user)

    def card_mean(self):
        response = self.client.get(reverse("protected_media", args=["order", self.order.pk, "id_front"]), {"card": "1"})
        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content) if response.streaming else response.content
        return np.asarray(Image.open(BytesIO(body)).convert("L"), dtype=np.float32).mean()

    def test_saved_from_print_preview_and_used_by_card_and_pdf(self):
        url = reverse("form_print_id_crop", args=[self.order.pk])
        self.assertEqual(self.client.post(url, {"side": "front", "crop": json.dumps(BASE)}).status_code, 200)
        plain_card = self.card_mean()
        plain_slot = form_print.PrintJob(self.order, "id_copy")
        form_print.build_forms_pdf([plain_slot])
        plain_pdf_card = np.asarray(plain_slot.id_slots[0]["card"].convert("L"), dtype=np.float32).mean()

        response = self.client.post(url, {"side": "front", "crop": json.dumps({**BASE, "brightness": 40, "sharpness": 30})})
        self.assertEqual(response.status_code, 200, response.content)
        self.order.refresh_from_db()
        self.assertEqual((self.order.id_front_crop["brightness"], self.order.id_front_crop["sharpness"]), (40, 30))
        self.assertEqual(OrderEvent.objects.filter(order=self.order, event_type="id_crop_adjusted").count(), 2)

        self.assertGreater(self.card_mean(), plain_card + 8, "訂單頁卡片圖（?card=1）套用亮度")
        job = form_print.PrintJob(self.order, "id_copy")
        form_print.build_forms_pdf([job])
        self.assertTrue(job.id_slots[0]["saved"])
        bright_pdf_card = np.asarray(job.id_slots[0]["card"].convert("L"), dtype=np.float32).mean()
        self.assertGreater(bright_pdf_card, plain_pdf_card + 8, "列印的影本套用亮度")
