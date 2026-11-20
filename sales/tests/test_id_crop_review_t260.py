"""T-260（使用者 2026-11-20「四角走 1」）：自動偵測抓到的四邊形貼到照片邊界、或對邊明顯不平行時，
要標「建議確認裁切」，請使用者手動調整。偵測演算法與候選四邊形不改，只加提醒。

起因：訂單 23665 的正面照，自動四角上緣貼在照片頂端（y=0）、下緣斜約 9°，長寬比與面積都在範圍內，
沒有被提醒，預覽與辨識都歪掉。全部用合成圖與合成座標，不含真實證件。
"""
import numpy as np
from django.test import SimpleTestCase
from PIL import Image

from sales.services import id_card_crop as crop
from sales.tests import id_card_synthetic as synthetic

# 23665 那種：上緣貼在照片頂端、下緣斜（正規化座標，照片 4032×3024）。
SNAPPED = [[0.138, 0.0], [0.879, 0.0], [0.88, 0.582], [0.125, 0.745]]


def pixels(normalized, size):
    width, height = size
    return np.array([[x * width, y * height] for x, y in normalized], dtype=np.float32)


class CropReviewBorderAndSkewTests(SimpleTestCase):
    def test_card_cut_by_photo_edge_is_flagged(self):
        # 卡片上緣超出照片頂端：偵測只抓得到貼著邊界的框。
        image = Image.fromarray(synthetic.scene("front", [[300, -60], [1250, -30], [1220, 700], [280, 650]]))
        params = crop.auto_params(image, "front")
        self.assertEqual(params["mode"], "auto")
        self.assertTrue(params["needs_review"])

    def test_snapped_and_skewed_quad_like_order_23665_is_flagged(self):
        src = np.zeros((3024, 4032, 3), dtype=np.uint8)
        reasons = crop.review_reasons(src, pixels(SNAPPED, (4032, 3024)), "front", True, None)
        self.assertIn("卡片貼到照片邊緣，可能沒抓準", reasons)
        self.assertIn("卡片對邊不平行，可能沒抓準", reasons)

    def test_skewed_quad_away_from_border_is_flagged(self):
        src = np.zeros((1200, 1600, 3), dtype=np.uint8)
        skewed = [[300, 250], [1250, 250], [1250, 700], [300, 900]]  # 下緣斜約 15°（門檻 8°）
        reasons = crop.review_reasons(src, np.array(skewed, dtype=np.float32), "front", True, None)
        self.assertIn("卡片對邊不平行，可能沒抓準", reasons)
        self.assertNotIn("卡片貼到照片邊緣，可能沒抓準", reasons)

    def test_normal_tilted_card_is_not_flagged(self):
        for side in ("front", "back"):
            with self.subTest(side=side):
                params = crop.auto_params(Image.fromarray(synthetic.scene(side)), side)
                self.assertFalse(params["needs_review"])
        src = np.zeros((1200, 1600, 3), dtype=np.uint8)
        self.assertEqual(crop.review_reasons(src, np.array(synthetic.TILTED, dtype=np.float32), None, True, None), [])
