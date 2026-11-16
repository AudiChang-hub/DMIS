"""T-190：證件四角偵測、上下判斷、透視裁切與裁切參數驗證（合成圖，不含真實證件）。"""
import io
import json
import time

import numpy as np
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image

from sales.services import id_card_crop as crop
from sales.tests import id_card_synthetic as synthetic


def max_error(found, expected):
    return float(np.abs(np.asarray(found) - np.float32(expected)).max())


class DetectCardTests(SimpleTestCase):
    def test_tilted_card_corners_found_within_tolerance(self):
        for side in ("front", "back"):
            with self.subTest(side=side):
                corners = crop.detect_card(synthetic.scene(side))
                # 容許照片長邊的 1%（16 px）。
                self.assertLess(max_error(corners, synthetic.TILTED), 16)

    def test_upside_down_and_upright_turns(self):
        for side in ("front", "back"):
            for upside_down, expected in ((False, 0), (True, 2)):
                with self.subTest(side=side, upside_down=upside_down):
                    image = synthetic.scene(side, upside_down=upside_down)
                    corners = crop.detect_card(image)
                    self.assertEqual(crop.detect_turn(image, corners, side), expected)

    def test_portrait_card_turns_to_landscape(self):
        # 卡片逆時針轉 90°：卡片左上角落在照片左下。
        corners_on_photo = [[400, 1100], [420, 150], [1000, 170], [980, 1090]]
        image = synthetic.scene("front", corners_on_photo, size=(1400, 1300))
        corners = crop.detect_card(image)
        turn = crop.detect_turn(image, corners, "front")
        card = crop.warp(image, corners, turn)
        self.assertEqual(card.shape[:2], (crop.CROP_HEIGHT, crop.CROP_WIDTH))
        self.assertGreater(crop.front_upright_score(card), 0)

    def test_barcode_wins_even_when_back_is_put_in_front_slot(self):
        image = synthetic.scene("back", upside_down=True)
        corners = crop.detect_card(image)
        self.assertEqual(crop.detect_turn(image, corners, "front"), 2)

    def test_resident_certificate_only_turns_to_landscape(self):
        image = synthetic.scene("front", upside_down=True)
        corners = crop.detect_card(image)
        self.assertEqual(crop.detect_turn(image, corners, None), 0)

    def test_card_inside_sleeve_prefers_inner_card(self):
        sleeve = [[240, 200], [1310, 250], [1280, 930], [220, 870]]
        image = synthetic.scene("front", sleeve=sleeve)
        self.assertLess(max_error(crop.detect_card(image), synthetic.TILTED), 16)

    def test_no_card_falls_back_to_full_image(self):
        image = synthetic.background((1200, 900))
        np.testing.assert_allclose(crop.detect_card(image), crop.full_image(1200, 900))

    def test_already_cropped_card_uses_whole_image(self):
        image = synthetic.card("front")
        corners = crop.detect_card(image)
        self.assertLess(max_error(corners, crop.full_image(image.shape[1], image.shape[0])), 12)

    def test_large_photo_is_fast_enough(self):
        image = synthetic.scene("front", [[750, 625], [3125, 750], [3050, 2200], [700, 2050]], size=(4000, 3000))
        started = time.monotonic()
        corners = crop.detect_card(image)
        elapsed = time.monotonic() - started
        self.assertLess(max_error(corners, [[750, 625], [3125, 750], [3050, 2200], [700, 2050]]), 40)
        self.assertLess(elapsed, 3.0)


class CropParamsTests(SimpleTestCase):
    def test_auto_params_round_trip_and_apply(self):
        image = synthetic.to_pil(synthetic.scene("front", upside_down=True))
        params = crop.auto_params(image, "front")
        self.assertEqual(params["mode"], "auto")
        self.assertEqual(params["turn"], 2)
        self.assertEqual((params["src_w"], params["src_h"]), image.size)
        self.assertEqual(crop.clean_params(params, image.size), params)
        card = crop.apply_crop(image, params)
        self.assertEqual(card.size, (crop.CROP_WIDTH, crop.CROP_HEIGHT))
        self.assertGreater(crop.front_upright_score(np.asarray(card)), 0)

    def test_auto_params_without_card_is_full_mode(self):
        image = synthetic.to_pil(synthetic.background((1200, 900)))
        params = crop.auto_params(image, "front")
        self.assertEqual(params["mode"], "full")
        self.assertEqual(params["corners"][0], [0.0, 0.0])

    def test_clean_params_rejects_other_photo_and_bad_values(self):
        params = crop.params_from_pixels(synthetic.TILTED, 1, (1600, 1200), "manual")
        self.assertIsNotNone(crop.clean_params(params, (1600, 1200)))
        self.assertIsNotNone(crop.clean_params(json.dumps(params), (1600, 1200)))
        self.assertIsNone(crop.clean_params(params, (1200, 1600)))
        self.assertIsNone(crop.clean_params({**params, "turn": 4}, (1600, 1200)))
        self.assertIsNone(crop.clean_params({**params, "v": 2}, (1600, 1200)))
        self.assertIsNone(crop.clean_params({**params, "corners": params["corners"][:3]}, (1600, 1200)))
        self.assertIsNone(crop.clean_params({**params, "corners": [[0, 0], [1, 1], [1, 0], [0, 1]]}, (1600, 1200)))
        self.assertIsNone(crop.clean_params({**params, "corners": [[0, 0], [9, 0], [1, 1], [0, 1]]}, (1600, 1200)))
        self.assertIsNone(crop.clean_params("not json", (1600, 1200)))
        self.assertIsNone(crop.clean_params("", (1600, 1200)))
        self.assertEqual(crop.clean_params({**params, "mode": "evil"}, (1600, 1200))["mode"], "manual")

    def test_oriented_size_applies_exif_rotation(self):
        data = synthetic.jpeg_bytes(synthetic.background((300, 200)), exif_orientation=6)
        upload = SimpleUploadedFile("photo.jpg", data, content_type="image/jpeg")
        self.assertEqual(crop.oriented_size(upload), (200, 300))
        self.assertEqual(crop.open_oriented(data).size, (200, 300))

    def test_open_oriented_rejects_non_image(self):
        with self.assertRaises(ValueError):
            crop.open_oriented(b"not an image")

    def test_full_image_params_are_landscape(self):
        params = crop.full_image_params((600, 900))
        self.assertEqual(params["mode"], "full")
        self.assertEqual(params["turn"], 3)
        card = crop.apply_crop(Image.new("RGB", (600, 900), "white"), params)
        self.assertEqual(card.size, (crop.CROP_WIDTH, crop.CROP_HEIGHT))


class SyntheticFixtureTests(SimpleTestCase):
    def test_jpeg_helper_produces_readable_image(self):
        data = synthetic.jpeg_bytes(synthetic.card("back"))
        self.assertEqual(Image.open(io.BytesIO(data)).size, (synthetic.CARD_W, synthetic.CARD_H))
