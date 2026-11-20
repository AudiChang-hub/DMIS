"""T-262 測試用合成身分證（不含真實證件）：照使用者描述的國民身分證版面特徵畫，比 id_card_synthetic 更接近實拍。

正面：淡黃底、放射細紋與中央浮水印；左上國旗、緊貼上緣的標題列；右側約三分之一的大頭照（上緣接近卡片頂）；
左半部姓名／出生年月日／發證日期，中間有水平分隔線；右下紅色統一編號。
反面：淡粉底、淡色橫線；由上而下父母、配偶與役別、出生地、住址兩行；左下長條碼貼近下緣；
右下金色圓形徽記，下方綠色流水號，貼近下緣與右緣。四角為圓角。
實拍情境：黑色織紋證件套（卡片外一圈深色邊，再外一圈透明反光邊）、桌面、輕微傾斜、iPhone 方向（EXIF 6／8，MPO）。

每個「貼邊元素」都用獨特顏色畫，測試可以檢查裁切結果有沒有保留：國旗紅藍、標題深藍、統一編號紅、條碼黑、徽記金、流水號綠。
"""
import io

import cv2
import numpy as np
from PIL import Image

CARD_W, CARD_H = 856, 540  # 85.6 × 54 mm，每 mm 10 px
RADIUS = 32  # 約 3.2 mm 圓角

MARKERS = {
    "front": {"flag_red": (200, 30, 40), "flag_blue": (20, 40, 150), "title": (30, 40, 90), "number": (210, 20, 20)},
    "back": {"barcode": (15, 15, 15), "seal": (205, 160, 40), "serial": (20, 140, 60)},
}


def _rounded_mask(width, height, radius):
    mask = np.zeros((height, width), np.uint8)
    cv2.rectangle(mask, (radius, 0), (width - radius, height), 255, -1)
    cv2.rectangle(mask, (0, radius), (width, height - radius), 255, -1)
    for cx, cy in ((radius, radius), (width - radius, radius), (radius, height - radius), (width - radius, height - radius)):
        cv2.circle(mask, (cx, cy), radius, 255, -1)
    return mask


def card(side):
    rng = np.random.default_rng(7 if side == "front" else 8)
    if side == "front":
        image = np.full((CARD_H, CARD_W, 3), (246, 238, 196), np.uint8)  # 淡黃
        center = (CARD_W // 2, CARD_H // 2)
        for angle in range(0, 360, 4):  # 放射細紋
            end = (int(center[0] + 900 * np.cos(np.radians(angle))), int(center[1] + 900 * np.sin(np.radians(angle))))
            cv2.line(image, center, end, (236, 226, 182), 1)
        cv2.circle(image, center, 120, (238, 228, 186), 6)  # 中央浮水印
        m = MARKERS["front"]
        cv2.rectangle(image, (18, 10), (88, 56), m["flag_red"], -1)  # 國旗，緊貼左上
        cv2.rectangle(image, (18, 10), (52, 32), m["flag_blue"], -1)
        cv2.rectangle(image, (104, 12), (560, 50), m["title"], -1)  # 標題列，緊貼上緣
        cv2.rectangle(image, (590, 24), (830, 330), (120, 110, 100), -1)  # 大頭照（上緣接近卡片頂）
        cv2.rectangle(image, (604, 40), (816, 316), (160, 140, 125), -1)
        for top in (90, 170, 250):  # 姓名、出生、發證；中間水平分隔線
            cv2.rectangle(image, (40, top), (330, top + 26), (70, 60, 50), -1)
            cv2.line(image, (30, top + 50), (560, top + 50), (150, 140, 110), 2)
        cv2.rectangle(image, (40, 330), (520, 350), (90, 80, 70), -1)
        cv2.rectangle(image, (600, 470), (830, 515), m["number"], -1)  # 右下紅色統一編號
    else:
        image = np.full((CARD_H, CARD_W, 3), (246, 222, 226), np.uint8)  # 淡粉
        for y in range(20, CARD_H, 22):
            cv2.line(image, (0, y), (CARD_W, y), (236, 210, 214), 1)
        for top in (40, 100, 160, 220, 270):  # 父母、配偶役別、出生地、住址兩行
            cv2.rectangle(image, (40, top), (40 + int(rng.integers(380, 720)), top + 22), (80, 70, 75), -1)
        m = MARKERS["back"]
        x = 40
        while x < 480:  # 左下長條碼，接近下緣
            width = int(rng.integers(2, 6))
            cv2.rectangle(image, (x, 400), (x + width, 520), m["barcode"], -1)
            x += width + int(rng.integers(2, 6))
        cv2.circle(image, (735, 410), 58, m["seal"], -1)  # 右下金色徽記
        cv2.rectangle(image, (650, 484), (836, 522), m["serial"], -1)  # 下方綠色流水號，貼近下緣與右緣
    mask = _rounded_mask(CARD_W, CARD_H, RADIUS)
    return image, mask


def _warp(source, mask, corners, size):
    height, width = source.shape[:2]
    matrix = cv2.getPerspectiveTransform(np.float32([[0, 0], [width, 0], [width, height], [0, height]]), np.float32(corners))
    warped = cv2.warpPerspective(source, matrix, size)
    warped_mask = cv2.warpPerspective(mask, matrix, size)
    return warped, warped_mask


def _table(size, seed=3):
    width, height = size
    rng = np.random.default_rng(seed)
    base = np.zeros((height, width, 3), np.uint8)
    base[:] = (150, 115, 80)  # 木頭桌面
    grain = rng.integers(0, 30, (height, 1, 1), dtype=np.uint8)
    base = cv2.add(base, np.repeat(np.repeat(grain, width, 1), 3, 2))
    noise = rng.integers(0, 18, (height, width, 1), dtype=np.uint8)
    return cv2.add(base, np.repeat(noise, 3, 2))


def _expand(corners, ratio):
    pts = np.float32(corners)
    center = pts.mean(axis=0)
    return center + (pts - center) * ratio


def scene(side="front", corners=None, size=(1600, 1200), sleeve=True):
    """corners：卡片四角（左上、右上、右下、左下）貼到照片上的位置。sleeve：外圍黑色織紋證件套＋透明反光邊。"""
    if corners is None:
        corners = [[330, 300], [1270, 330], [1250, 920], [310, 890]]  # 輕微傾斜
    image = _table(size)
    size_wh = (size[0], size[1])
    if sleeve:
        clear = np.full((CARD_H, CARD_W, 3), (205, 210, 212), np.uint8)  # 透明塑膠反光邊
        warped, mask = _warp(clear, np.full((CARD_H, CARD_W), 255, np.uint8), _expand(corners, 1.12), size_wh)
        image[mask > 0] = (0.45 * image[mask > 0] + 0.55 * warped[mask > 0]).astype(np.uint8)
        rng = np.random.default_rng(5)
        weave = np.full((CARD_H, CARD_W, 3), 28, np.uint8)  # 黑色織紋
        weave = cv2.add(weave, np.repeat(rng.integers(0, 22, (CARD_H, CARD_W, 1), dtype=np.uint8), 3, 2))
        for y in range(0, CARD_H, 6):
            cv2.line(weave, (0, y), (CARD_W, y), (44, 44, 44), 1)
        warped, mask = _warp(weave, np.full((CARD_H, CARD_W), 255, np.uint8), _expand(corners, 1.06), size_wh)
        image[mask > 0] = warped[mask > 0]
    source, card_mask = card(side)
    warped, mask = _warp(source, card_mask, corners, size_wh)
    image[mask > 0] = warped[mask > 0]
    return image


def iphone_jpeg(displayed, orientation):
    """把顯示用的照片存成 iPhone 相機那種「橫的像素＋EXIF 方向」，帶附屬影像（Pillow 讀作 MPO）。"""
    image = Image.fromarray(displayed)
    raw = {6: image.transpose(Image.Transpose.ROTATE_90), 8: image.transpose(Image.Transpose.ROTATE_270)}.get(orientation, image)
    exif = Image.Exif()
    if orientation in (6, 8):
        exif[0x0112] = orientation
    output = io.BytesIO()
    raw.save(output, "MPO", save_all=True, append_images=[raw.resize((raw.width // 4, raw.height // 4))], exif=exif, quality=90)
    return output.getvalue()


def marker_present(card_image, color, tolerance=40, min_pixels=30):
    """裁切結果裡有沒有這個顏色的元素（貼邊元素是否被切掉）。"""
    diff = np.abs(card_image.astype(int) - np.array(color, int)).sum(axis=2)
    return int((diff < tolerance).sum()) >= min_pixels
