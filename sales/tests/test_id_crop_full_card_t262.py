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
from PIL import Image

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


class CameraCaptureOrientationTests(SimpleTestCase):
    """T-262 續（使用者 2026-11-20：「手機橫拿、證件橫放」；從圖庫選圖正常、直接拍照上傳才歪；
    「應該直拿橫拿都要可以完成，不應該有差」）。

    重現：卡片幾乎填滿畫面時，邊緣微調（可平移到 30%）把上緣拉到標題列下緣那條強直線，國旗與標題列被切掉。
    與 EXIF 無關：橫拍 EXIF 1／3、直拍「像素未轉正＋EXIF 6／8」、「像素已轉正卻仍帶 EXIF 6／8」（伺服器多轉 90°）結果相同。
    修正：大幅微調只能把框補大、不能往內縮。"""

    FILLS = [[20, 70], [1996, 80], [1994, 1440], [18, 1432]]  # 2016×1512 橫幅照片，卡片幾乎填滿
    NORMAL = [[300, 330], [1720, 360], [1700, 1250], [280, 1220]]

    def photo(self, side, corners, orientation, already_upright):
        displayed = Image.fromarray(real.scene(side, corners, size=(2016, 1512), sleeve=False))
        if orientation in (6, 8) and not already_upright:
            raw = displayed.transpose(Image.Transpose.ROTATE_90 if orientation == 6 else Image.Transpose.ROTATE_270)
        elif orientation == 3:
            raw = displayed.transpose(Image.Transpose.ROTATE_180)
        else:
            raw = displayed
        exif = Image.Exif()
        if orientation != 1:
            exif[0x0112] = orientation
        import io as _io
        output = _io.BytesIO()
        raw.save(output, "MPO", save_all=True, append_images=[raw.resize((raw.width // 4, raw.height // 4))], exif=exif, quality=90)
        return crop.open_oriented(output.getvalue())

    def test_every_capture_variant_keeps_flag_title_and_number(self):
        variants = [(1, False), (3, False), (6, False), (8, False), (6, True), (8, True)]
        for corners in (self.FILLS, self.NORMAL):
            for orientation, already_upright in variants:
                with self.subTest(corners=corners[0], orientation=orientation, already_upright=already_upright):
                    image = self.photo("front", corners, orientation, already_upright)
                    params = crop.auto_params(image, "front")
                    card = np.asarray(crop.apply_crop(image, params, 856, 540))
                    for name, color in real.MARKERS["front"].items():
                        self.assertTrue(real.marker_present(card, color), name)

    def test_back_keeps_barcode_seal_and_serial_when_card_fills_frame(self):
        for orientation, already_upright in [(1, False), (3, False), (6, False), (6, True)]:
            with self.subTest(orientation=orientation, already_upright=already_upright):
                image = self.photo("back", self.FILLS, orientation, already_upright)
                card = np.asarray(crop.apply_crop(image, crop.auto_params(image, "back"), 856, 540))
                for name, color in real.MARKERS["back"].items():
                    self.assertTrue(real.marker_present(card, color), name)

    def test_far_refine_never_shrinks_the_card(self):
        image = np.asarray(Image.fromarray(real.scene("front", self.FILLS, size=(2016, 1512), sleeve=False)))
        quad = crop.detect_card(image)
        self.assertLess(min(y for _, y in quad), 0.07 * 1512)  # 上緣在卡片頂（約 5%），不在標題列下緣（約 13%）
