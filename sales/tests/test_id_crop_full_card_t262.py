"""T-262（使用者 2026-11-20「整個身分證的正反面都要完整的在框中」）：自動裁切要包住整張卡片。

- 抓到卡片外緣後每邊再往外多留約 2.5%（只多一小圈證件套，不留大片桌面）。
- 抓到的框和身分證比例差很多（多半只框到某一區塊）：不硬裁，保留整張照片並標「建議確認裁切」。
合成圖照國民身分證版面畫（id_card_realistic）：有／無黑色證件套、輕微傾斜、iPhone 方向（EXIF 6／8、MPO）；
正反面都要包含四個角與貼邊元素（國旗、標題、統一編號、條碼、徽記、流水號）。不含真實證件。
"""
from unittest import mock

import cv2
import numpy as np
from django.test import SimpleTestCase

from sales.services import id_card_crop as crop
from sales.tests import id_card_realistic as real

TILTED = [[330, 300], [1270, 330], [1250, 920], [310, 890]]
STRAIGHT = [[300, 280], [1300, 280], [1300, 911], [300, 911]]


def contains(quad, points, slack=2.0):
    contour = np.asarray(quad, np.float32).reshape(-1, 1, 2)
    return all(cv2.pointPolygonTest(contour, (float(x), float(y)), True) >= -slack for x, y in points)


class FullCardCropTests(SimpleTestCase):
    def test_crop_contains_whole_card_and_edge_elements(self):
        for side in ("front", "back"):
            for corners in (TILTED, STRAIGHT):
                for sleeve in (True, False):
                    for orientation in (1, 6, 8):
                        with self.subTest(side=side, corners=corners[0], sleeve=sleeve, orientation=orientation):
                            image = crop.open_oriented(real.iphone_jpeg(real.scene(side, corners, sleeve=sleeve), orientation))
                            params = crop.auto_params(image, side)
                            self.assertEqual(params["mode"], "auto")
                            self.assertTrue(contains(crop.pixel_corners(params), corners))
                            card = np.asarray(crop.apply_crop(image, params, 856, 540))
                            for name, color in real.MARKERS[side].items():
                                self.assertTrue(real.marker_present(card, color), name)

    def test_crop_stays_tight(self):
        # 只多一小圈：框的面積不超過卡片的 1.2 倍，不會留下大片桌面。
        image = crop.open_oriented(real.iphone_jpeg(real.scene("back", TILTED, sleeve=False), 1))
        quad = crop.pixel_corners(crop.auto_params(image, "back"))
        card_area = abs(cv2.contourArea(np.float32(TILTED)))
        self.assertLess(abs(cv2.contourArea(quad)) / card_area, 1.2)

    def test_wrong_aspect_keeps_whole_photo_and_asks_to_check(self):
        # 只框到上半部（比例 3:1）：不硬裁成錯的卡片。
        image = crop.open_oriented(real.iphone_jpeg(real.scene("front", TILTED), 1))
        strip = np.float32([[330, 300], [1270, 330], [1265, 500], [325, 470]])
        with mock.patch.object(crop, "detect_card", return_value=strip):
            params = crop.auto_params(image, "front")
        self.assertEqual(params["mode"], "full")
        self.assertTrue(params["needs_review"])

    def test_expand_quad_is_clamped_to_photo(self):
        grown = crop.expand_quad([[0, 0], [100, 0], [100, 60], [0, 60]], 0.025, 101, 61)
        self.assertGreaterEqual(grown.min(), 0)
        self.assertLessEqual(grown[:, 0].max(), 100)
        self.assertLessEqual(grown[:, 1].max(), 60)


class PhotoBlockFalseHitTests(SimpleTestCase):
    """T-262 續（2.32.3 上線後 17:46 實拍「一樣」）：淺色卡片放在淺色桌面、沒有證件套、手機直拍，
    卡片外緣對比太低，偵測抓到大頭照框（直式、比例剛好接近身分證），裁成一小塊又轉 90°，雖然有提醒卻仍然裁切。
    改為：抓到的框不到畫面 10% 就視為抓錯，保留整張照片（照拍攝方向，不轉）並提醒確認。"""

    PORTRAIT_SHOT = [[110, 520], [1090, 545], [1080, 1160], [100, 1135]]  # 直拍照片（1200×1600）裡橫放的卡片

    def test_photo_block_is_not_used_as_the_card(self):
        for desk in ((238, 236, 230), (240, 232, 205)):
            for orientation in (6, 8):
                with self.subTest(desk=desk, orientation=orientation):
                    displayed = real.scene("front", self.PORTRAIT_SHOT, size=(1200, 1600), sleeve=False, desk=desk, flat_desk=True)
                    params = crop.auto_params(crop.open_oriented(real.iphone_jpeg(displayed, orientation)), "front")
                    self.assertEqual(params["mode"], "full")
                    self.assertEqual(params["turn"], 0)
                    self.assertTrue(params["needs_review"])

    def test_card_in_sleeve_on_light_desk_is_still_cropped(self):
        displayed = real.scene("front", self.PORTRAIT_SHOT, size=(1200, 1600), sleeve=True, desk=(238, 236, 230), flat_desk=True)
        params = crop.auto_params(crop.open_oriented(real.iphone_jpeg(displayed, 6)), "front")
        self.assertEqual(params["mode"], "auto")
        self.assertTrue(contains(crop.pixel_corners(params), self.PORTRAIT_SHOT))

    def test_preview_shows_whole_photo_as_shot_in_full_mode(self):
        from pathlib import Path
        from django.conf import settings

        script = (Path(settings.BASE_DIR) / "templates" / "sales" / "_order_form_scripts.html").read_text(encoding="utf-8")
        self.assertIn('const whole = params.mode === "full";', script)
        self.assertIn("canvas.style.aspectRatio = whole ? `${preview.naturalWidth} / ${preview.naturalHeight}` : \"\";", script)
        self.assertIn("const drawParams = whole ? {...params, turn: 0} : params;", script)
