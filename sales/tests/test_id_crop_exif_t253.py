"""T-253（使用者 2026-11-20「上傳證件的部分，他的圖片會異常扭曲，造成辨識出問題」）：

同一張直拍、卡片轉 90° 的照片，存成一般 JPEG、或 iPhone 相機那種「橫的像素＋EXIF 方向 6／8」，
伺服器（自動偵測、裁切、辨識前的轉正）看到的尺寸、四角與轉向都要一樣，裁出來的卡片是正的。
瀏覽器端依 EXIF 轉正快照的部分見 tests/frontend/id-crop-orientation.test.cjs。全部用合成圖，不含真實證件。
"""
import numpy as np
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image

from sales.services import id_card_crop as crop
from sales.tests import id_card_synthetic as synthetic

# 直式照片（顯示時 1200×1600），卡片逆時針轉 90°。
CORNERS = [[300, 1300], [330, 350], [920, 370], [890, 1320]]
# 存檔時把像素轉成橫的，再寫 EXIF 方向，讓「套用 EXIF 後」等於顯示的樣子。
RAW_TRANSPOSE = {6: Image.Transpose.ROTATE_90, 8: Image.Transpose.ROTATE_270}


class IdCropExifOrientationTests(SimpleTestCase):
    def setUp(self):
        self.displayed = Image.fromarray(synthetic.scene("front", CORNERS, size=(1200, 1600)))
        self.files = {1: synthetic.jpeg_bytes(np.asarray(self.displayed))}
        for orientation, transpose in RAW_TRANSPOSE.items():
            self.files[orientation] = synthetic.jpeg_bytes(np.asarray(self.displayed.transpose(transpose)), exif_orientation=orientation)

    def test_raw_pixels_are_landscape_but_oriented_size_matches_display(self):
        for orientation, data in self.files.items():
            with self.subTest(orientation=orientation):
                upload = SimpleUploadedFile("image.jpg", data, content_type="image/jpeg")
                self.assertEqual(crop.oriented_size(upload), (1200, 1600))
                self.assertEqual(crop.open_oriented(data).size, (1200, 1600))

    def test_auto_params_and_card_are_the_same_for_every_orientation(self):
        reference = crop.auto_params(crop.open_oriented(self.files[1]), "front")
        self.assertEqual(reference["mode"], "auto")
        self.assertIn(reference["turn"], (1, 3))
        for orientation in (6, 8):
            with self.subTest(orientation=orientation):
                oriented = crop.open_oriented(self.files[orientation])
                params = crop.auto_params(oriented, "front")
                self.assertEqual((params["src_w"], params["src_h"], params["turn"]), (reference["src_w"], reference["src_h"], reference["turn"]))
                self.assertLess(np.abs(np.array(params["corners"]) - np.array(reference["corners"])).max(), 0.01)
                card = np.asarray(crop.apply_crop(oriented, params, 320, 202))
                self.assertGreater(crop.front_upright_score(card), 0)
