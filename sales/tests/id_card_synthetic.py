"""測試用的合成證件照（T-190）：真實證件照片不得進 repo，這裡只畫出身分證的版面特徵。

正面：淺色卡、右側深色大頭照塊、左側文字列。反面：右上文字列、左下條碼紋。
"""
import io

import cv2
import numpy as np
from PIL import Image


CARD_W, CARD_H = 856, 540


def card(side):
    image = np.full((CARD_H, CARD_W, 3), 228, np.uint8)
    rng = np.random.default_rng(1)
    if side == "front":
        cv2.rectangle(image, (int(.72 * CARD_W), int(.22 * CARD_H)), (int(.94 * CARD_W), int(.82 * CARD_H)), (95, 100, 105), -1)
        for index, y in enumerate((.12, .3, .42, .54, .66)):
            top = int(y * CARD_H)
            cv2.rectangle(image, (int(.06 * CARD_W), top), (int(.06 * CARD_W) + 200 + 30 * index, top + 14), (60, 60, 60), -1)
        cv2.rectangle(image, (int(.06 * CARD_W), int(.85 * CARD_H)), (int(.5 * CARD_W), int(.85 * CARD_H) + 22), (40, 40, 40), -1)
    else:
        for y in (.1, .2, .3, .4, .5):
            top = int(y * CARD_H)
            cv2.rectangle(image, (int(.3 * CARD_W), top), (int(.9 * CARD_W), top + 12), (70, 70, 70), -1)
        x = int(.06 * CARD_W)
        while x < int(.58 * CARD_W):
            width = int(rng.integers(2, 6))
            cv2.rectangle(image, (x, int(.73 * CARD_H)), (x + width, int(.9 * CARD_H)), (20, 20, 20), -1)
            x += width + int(rng.integers(2, 6))
    return image


def paste(background, source, corners):
    height, width = source.shape[:2]
    matrix = cv2.getPerspectiveTransform(
        np.float32([[0, 0], [width, 0], [width, height], [0, height]]), np.float32(corners)
    )
    size = (background.shape[1], background.shape[0])
    warped = cv2.warpPerspective(source, matrix, size)
    mask = cv2.warpPerspective(np.full((height, width), 255, np.uint8), matrix, size)
    background[mask > 0] = warped[mask > 0]
    return background


def background(size=(1600, 1200)):
    width, height = size
    base = np.full((height, width, 3), 70, np.uint8)
    noise = np.random.default_rng(2).integers(0, 25, (height, width, 1), dtype=np.uint8)
    return cv2.add(base, np.repeat(noise, 3, 2))


TILTED = [[300, 250], [1250, 300], [1220, 880], [280, 820]]


def scene(side="front", corners=TILTED, size=(1600, 1200), upside_down=False, sleeve=None):
    """corners：卡片（正立時的）左上、右上、右下、左下貼到照片上的位置。"""
    source = card(side)
    if upside_down:
        source = source[::-1, ::-1].copy()
    image = background(size)
    if sleeve:
        paste(image, np.full((CARD_H, CARD_W, 3), 150, np.uint8), sleeve)
    return paste(image, source, corners)


def to_pil(array):
    return Image.fromarray(array)


def jpeg_bytes(array, exif_orientation=None):
    output = io.BytesIO()
    image = Image.fromarray(array)
    if exif_orientation:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        image.save(output, format="JPEG", quality=90, exif=exif)
    else:
        image.save(output, format="JPEG", quality=90)
    return output.getvalue()
