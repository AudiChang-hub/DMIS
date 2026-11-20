"""T-262（使用者 2026-11-20「整個身分證的正反面都要完整的在框中」）：自動裁切要包住整張卡片。

- 抓到卡片外緣後每邊再往外多留約 3%（AUTO_MARGIN；只多一小圈證件套，不留大片桌面）。
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
        self.assertEqual(params["turn"], 0)
        self.assertTrue(params["needs_review"])

    def test_card_not_found_keeps_whole_photo_as_shot(self):
        """T-262 驗收（2.32.5）：找不到卡片、自動改用整張照片時也不轉向（原本可能帶 turn 1／3，
        訂單頁預覽不轉、列印卻轉了，兩邊不一致）。"""
        image = crop.open_oriented(real.iphone_jpeg(real.scene("front", TILTED), 1))
        whole = crop.full_image(*image.size)
        with mock.patch.object(crop, "detect_card", return_value=whole), \
                mock.patch.object(crop, "_turn_decision", return_value=(3, 0.0)):
            params = crop.auto_params(image, "front")
        self.assertEqual(params["mode"], "full")
        self.assertEqual(params["turn"], 0)
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

    def test_preview_uses_shared_preview_shape(self):
        """訂單頁卡片預覽怎麼畫由 id-crop-editor.js 的 previewShape 決定（行為測試在
        tests/frontend/id-crop-preview-shape-t262.test.cjs）：只有自動改用整張照片、還沒確認的才不轉向。"""
        from pathlib import Path
        from django.conf import settings

        script = (Path(settings.BASE_DIR) / "templates" / "sales" / "_order_form_scripts.html").read_text(encoding="utf-8")
        self.assertIn("const {whole, params: drawParams} = window.dmisIdCrop.previewShape(params);", script)
        self.assertNotIn('const whole = params.mode === "full";', script)


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

    VARIANTS = [(1, False), (3, False), (6, False), (8, False), (6, True), (8, True)]

    @staticmethod
    def server_frame(points_or_mask, orientation, already_upright, size=(2016, 1512)):
        """拍攝畫面上的卡片四角（或卡片遮罩）換到伺服器轉正後的座標。只有「像素已轉正卻仍帶 EXIF 6／8」
        會被伺服器多轉 90°（exif_transpose：6＝ROTATE_270、8＝ROTATE_90）；其他情況伺服器看到的就是拍攝畫面。"""
        width, height = size
        if isinstance(points_or_mask, np.ndarray):
            if not already_upright:
                return points_or_mask
            turn = Image.Transpose.ROTATE_270 if orientation == 6 else Image.Transpose.ROTATE_90
            return np.asarray(Image.fromarray(points_or_mask).transpose(turn))
        if not already_upright:
            return points_or_mask
        if orientation == 6:
            return [[height - 1 - y, x] for x, y in points_or_mask]
        return [[y, width - 1 - x] for x, y in points_or_mask]

    def assert_whole_card_kept(self, side, corners, orientation, already_upright):
        image = self.photo(side, corners, orientation, already_upright)
        params = crop.auto_params(image, side)
        self.assertEqual(params["mode"], "auto")
        quad = crop.pixel_corners(params)
        # 四角：卡片的四個角都在裁切框內。
        self.assertTrue(contains(quad, self.server_frame(corners, orientation, already_upright)), "四角")
        # 圓角也算：照片上每一個卡片像素都在框內。
        _, card_mask = real.card(side)
        _, mask = real._warp(card_mask, card_mask, corners, (2016, 1512))
        mask = self.server_frame(mask, orientation, already_upright) > 0
        inside = np.zeros(mask.shape, np.uint8)
        cv2.fillConvexPoly(inside, np.round(quad).astype(np.int32), 1)
        self.assertEqual(int((mask & (inside == 0)).sum()), 0, "卡片像素跑到框外")
        # 貼邊元素。
        card = np.asarray(crop.apply_crop(image, params, 856, 540))
        for name, color in real.MARKERS[side].items():
            self.assertTrue(real.marker_present(card, color), name)

    def test_every_capture_variant_keeps_flag_title_and_number(self):
        for corners in (self.FILLS, self.NORMAL):
            for orientation, already_upright in self.VARIANTS:
                with self.subTest(corners=corners[0], orientation=orientation, already_upright=already_upright):
                    self.assert_whole_card_kept("front", corners, orientation, already_upright)

    def test_back_keeps_corners_barcode_seal_and_serial_in_every_variant(self):
        """T-262 驗收（2.32.5）：EXIF 3、像素已轉正仍帶 EXIF 6／8 也要斷言四角。卡片填滿畫面時，近距微調曾把下緣吸到
        條碼下緣（往內 1.7–3%），輪廓也曾整條斜進卡片：四角差 16–41 px。"""
        for corners in (self.FILLS, self.NORMAL):
            for orientation, already_upright in self.VARIANTS:
                with self.subTest(corners=corners[0], orientation=orientation, already_upright=already_upright):
                    self.assert_whole_card_kept("back", corners, orientation, already_upright)

    def test_portrait_card_near_top_keeps_flag_and_title(self):
        """2.32.6（T-262 複驗回歸，驗收隨機組種子 23 第 22 張）：直式照片、卡片靠近上緣、沒有證件套。
        2.32.5 先把近距結果補邊才判斷要不要採用大幅微調，多出來的區域只剩深色標題列，正確的大幅微調不被採用：
        上緣斜進標題列、國旗被切掉，也沒有提醒。"""
        corners = [[385.5, 43.2], [1167.6, 47.4], [1148.3, 549.4], [416.0, 537.3]]
        image = Image.fromarray(real.scene("front", corners, size=(1200, 1600), sleeve=False, desk=(150, 115, 80)))
        params = crop.auto_params(image, "front")
        self.assertEqual(params["mode"], "auto")
        quad = crop.pixel_corners(params)
        self.assertTrue(contains(quad, corners), "四角")
        matrix = cv2.getPerspectiveTransform(np.float32([[0, 0], [856, 0], [856, 540], [0, 540]]), np.float32(corners))
        top = cv2.perspectiveTransform(np.float32([[[18, 10], [300, 12], [560, 12]]]), matrix)[0]
        self.assertTrue(contains(quad, top), "國旗與標題上緣")
        card = np.asarray(crop.apply_crop(image, params, 856, 540))
        for name, color in real.MARKERS["front"].items():
            self.assertTrue(real.marker_present(card, color), name)

    def test_far_refine_never_shrinks_the_card(self):
        image = np.asarray(Image.fromarray(real.scene("front", self.FILLS, size=(2016, 1512), sleeve=False)))
        quad = crop.detect_card(image)
        self.assertLess(min(y for _, y in quad), 0.07 * 1512)  # 上緣在卡片頂（約 5%），不在標題列下緣（約 13%）
