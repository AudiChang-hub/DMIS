"""身分證／居留證照片：偵測卡片四角、判斷上下、透視裁切成 85.6×54 mm（T-190 方案 A）。

演算法移植自使用者的「身分證排版工具」（C#／OpenCvSharp 的 ImageOps：DetectCard、Refine、
DetectTurn、Warp），參數與門檻保持一致，改動處都有註記。原始照片一律不改，只存裁切參數：

    {"v": 1, "corners": [[x, y] × 4], "turn": 0-3, "src_w": 寬, "src_h": 高,
     "mode": "auto|manual|full", "by_ocr": false}

- corners：卡片四角在原圖（已套用 EXIF 方向）上的 0–1 正規化座標，順時針 左上、右上、右下、左下。
- turn：以 corners[turn]→corners[turn+1] 這條邊作為輸出的上緣（與 C# 相同）。
- src_w／src_h：參數所屬照片的尺寸；換了照片尺寸不符時參數視為無效。
"""
import io
import math
import warnings
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError


CROP_WIDTH = 1012  # 85.6 mm @ 300 dpi
# 「建議確認裁切」的門檻（T-200）：只在明顯沒把握時提醒，正常卡片不標，避免使用者對提醒麻木。
# 合成證件圖量測：正常卡片比例偏差約 0.04、佔畫面 28%、正面方向分數約 77、反面約 270。
REVIEW_ASPECT_DEVIATION = 0.18  # 四邊形長寬比與 85.6:54 相差約 20% 以上（強烈透視或抓錯框）
REVIEW_MIN_AREA = 0.03  # 卡片不到畫面 3%（拍得太遠或抓到卡片上的小色塊）
REVIEW_MIN_FRONT_SCORE = 12  # 國民身分證正面：大頭照與左側文字區亮度差太小，上下方向沒把握
REVIEW_MIN_BACK_SCORE = 20  # 國民身分證反面：條碼區與對稱區的水平梯度差太小
# T-260（使用者 2026-11-20「四角走 1」）：只加提醒、不改偵測。
REVIEW_BORDER_MARGIN = 0.01  # 任一角離照片邊界不到長寬的 1%：卡片被照片切到或框貼到邊緣，多半沒抓準
REVIEW_MAX_SKEW_DEGREES = 8.0  # 上下（或左右）兩邊的方向差超過 8°：一般斜拍約 1–3°，明顯不平行表示抓錯邊
CACHE_VERSION = 2  # 2.32.5（T-262 驗收）：偵測改了，舊的自動偵測快取不再沿用
CROP_HEIGHT = 638  # 54 mm @ 300 dpi
CARD_ASPECT = 85.6 / 54.0
# T-262（使用者 2026-11-20「整個身分證的正反面都要完整的在框中」）：自動裁切抓到卡片外緣後，每邊再往外多留約 3%，
# 抓得略小也不會切到國旗、標題、條碼等貼邊內容；只多一小圈證件套，不留大片桌面。手動調整不受影響。
AUTO_MARGIN = 0.03
# 抓到的框比例和身分證差這麼多（約 1.12 以下或 2.25 以上）就不是整張卡片，多半只框到某一區塊：不裁，保留整張照片並提醒。
# 強烈斜拍但抓對的卡片約差 0.25，只提醒（REVIEW_ASPECT_DEVIATION）不放棄裁切。
FAIL_ASPECT_DEVIATION = 0.35
# T-262 續（17:46 實拍「一樣」）：淺色卡片放在淺色桌面、沒有證件套時，卡片外緣對比太低，大頭照框（直式、比例剛好接近
# 身分證）會被當成卡片，裁成一小塊又轉 90°。一般拍證件時卡片約佔畫面 20–60%，抓到的框不到 10% 就視為抓錯，不裁。
FAIL_MIN_AREA = 0.10
PARAMS_VERSION = 1
MODES = ("auto", "manual", "full")
MAX_SOURCE_PIXELS = 24_000_000

_KERNEL = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))


# ---------- 讀圖 ----------

def open_oriented(source):
    """bytes 或檔案物件 → 已套用 EXIF 方向的 RGB PIL 圖。無法辨識時丟 ValueError。"""
    try:
        if isinstance(source, (bytes, bytearray)):
            source = io.BytesIO(source)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source) as raw:
                if raw.width * raw.height > MAX_SOURCE_PIXELS:
                    raise ValueError("照片解析度過大。")
                return ImageOps.exif_transpose(raw).convert("RGB")
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValueError("檔案不是可辨識的照片。") from exc


def _header_size(handle):
    with Image.open(handle) as image:
        width, height = image.size
        orientation = image.getexif().get(0x0112, 1)
    return (height, width) if orientation in (5, 6, 7, 8) else (width, height)


def oriented_size(file_field):
    """只讀檔頭取得套用 EXIF 方向後的尺寸；讀不到回傳 None。

    已存檔的欄位從 storage 另開檔案讀；剛上傳、尚未存檔的檔案就地讀完再把讀取位置還原，
    不關閉它（之後還要存檔）。
    """
    try:
        if getattr(file_field, "_committed", False) and getattr(file_field, "name", ""):
            with file_field.storage.open(file_field.name, "rb") as handle:
                return _header_size(handle)
        handle = getattr(file_field, "file", file_field)
        position = handle.tell()
        handle.seek(0)
        try:
            return _header_size(handle)
        finally:
            handle.seek(position)
    except (OSError, ValueError, SyntaxError, AttributeError):
        return None


# ---------- 模型欄位（SalesOrder／OrderDraft 的 id_front_crop、id_back_crop） ----------

CROP_FIELDS = {"id_front": "id_front_crop", "id_back": "id_back_crop"}


def apply_posted_crops(instance, data, *, changed=()):
    """依表單送來的 id_front_crop／id_back_crop 更新裁切參數，回傳有變動的照片欄位。

    changed：這次換掉或移除的照片欄位——舊參數一律作廢，只接受與新照片尺寸相符的參數。
    照片沒換時，送來的參數有效才更新；空白或無效的參數不覆蓋既有值（避免舊分頁蓋掉）。
    """
    updated = []
    for photo_field, crop_field in CROP_FIELDS.items():
        raw = data.get(crop_field, "")
        if photo_field not in changed and not raw:
            continue
        file_field = getattr(instance, photo_field)
        size = oriented_size(file_field) if file_field and raw else None
        params = clean_params(raw, size) if size else None
        if photo_field not in changed and params is None:
            continue
        if getattr(instance, crop_field) != params:
            setattr(instance, crop_field, params)
            updated.append(photo_field)
    return updated


# ---------- 參數 ----------

def clean_params(raw, size):
    """驗證並正規化裁切參數；無效或不屬於這張照片（尺寸不符）回傳 None。"""
    import json

    if not raw:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(raw, dict) or raw.get("v") != PARAMS_VERSION:
        return None
    try:
        width, height = int(raw["src_w"]), int(raw["src_h"])
        turn = int(raw["turn"])
        corners = [[float(x), float(y)] for x, y in raw["corners"]]
    except (KeyError, TypeError, ValueError):
        return None
    if size is not None and (width, height) != tuple(size):
        return None
    if width <= 0 or height <= 0 or turn not in range(4) or len(corners) != 4:
        return None
    if not all(math.isfinite(v) and -0.05 <= v <= 1.05 for point in corners for v in point):
        return None
    pixel = np.array([[x * width, y * height] for x, y in corners], dtype=np.float32)
    if abs(cv2.contourArea(pixel)) < width * height * 0.005:
        return None
    if not cv2.isContourConvex(pixel.astype(np.int32)):
        return None
    mode = raw.get("mode") if raw.get("mode") in MODES else "manual"
    params = {
        "v": PARAMS_VERSION,
        "corners": [[round(x, 5), round(y, 5)] for x, y in corners],
        "turn": turn,
        "src_w": width,
        "src_h": height,
        "mode": mode,
        "by_ocr": bool(raw.get("by_ocr")),
        # 使用者手動調整（或在視窗按「套用」）過就不再提醒。
        "needs_review": bool(raw.get("needs_review")) and mode != "manual",
    }
    # 亮度／清晰度（T-220，照身分證排版工具）：選填，0 不存，舊參數照舊。
    for key, low, high in (("brightness", MIN_BRIGHTNESS, MAX_BRIGHTNESS), ("sharpness", 0, MAX_SHARPNESS)):
        try:
            value = int(round(float(raw.get(key) or 0)))
        except (TypeError, ValueError, OverflowError):
            value = 0
        value = min(max(value, low), high)
        if value:
            params[key] = value
    return params


def params_from_pixels(corners, turn, size, mode):
    width, height = size
    return {
        "v": PARAMS_VERSION,
        "corners": [[round(float(x) / width, 5), round(float(y) / height, 5)] for x, y in corners],
        "turn": int(turn) % 4,
        "src_w": width,
        "src_h": height,
        "mode": mode,
        "by_ocr": False,
        "needs_review": False,
    }


def pixel_corners(params):
    width, height = params["src_w"], params["src_h"]
    return np.array([[x * width, y * height] for x, y in params["corners"]], dtype=np.float32)


def turned(params, turn, *, by_ocr=False):
    return {**params, "turn": int(turn) % 4, "by_ocr": by_ocr}


def full_image_params(size):
    return params_from_pixels(full_image(*size), auto_turn(full_image(*size)), size, "full")


def review_reasons(src, corners, side, found_card, turn_score):
    """自動偵測沒把握的原因；空的就不提醒。"""
    if not found_card:
        return ["找不到卡片邊緣，用整張圖片"]
    reasons = []
    width, height = _side_lengths(corners)
    ratio = max(width, height) / max(1.0, min(width, height))
    if abs(math.log(ratio / CARD_ASPECT)) > REVIEW_ASPECT_DEVIATION:
        reasons.append("卡片比例和身分證差很多")
    if abs(cv2.contourArea(np.asarray(corners, dtype=np.float32))) / float(src.shape[0] * src.shape[1]) < REVIEW_MIN_AREA:
        reasons.append("卡片在照片裡太小")
    quad = np.asarray(corners, dtype=np.float32)
    src_h, src_w = src.shape[:2]
    margin_x, margin_y = src_w * REVIEW_BORDER_MARGIN, src_h * REVIEW_BORDER_MARGIN
    if any(x <= margin_x or x >= src_w - 1 - margin_x or y <= margin_y or y >= src_h - 1 - margin_y for x, y in quad):
        reasons.append("卡片貼到照片邊緣，可能沒抓準")
    if max(_edge_skew(quad[0], quad[1], quad[3], quad[2]), _edge_skew(quad[0], quad[3], quad[1], quad[2])) > REVIEW_MAX_SKEW_DEGREES:
        reasons.append("卡片對邊不平行，可能沒抓準")
    if turn_score is not None:
        score, used = turn_score
        if abs(score) < (REVIEW_MIN_BACK_SCORE if used == "back" else REVIEW_MIN_FRONT_SCORE):
            reasons.append("看不出上下方向")
    return reasons


def auto_params(image, side=None):
    """自動偵測：回傳參數；side 為 "front"／"back" 時依國民身分證版面判斷上下，None 只轉成橫式。

    needs_review：偵測沒把握（見 review_reasons）時為 True，畫面標「建議確認裁切」。
    """
    src = np.asarray(image)
    corners = detect_card(src)
    turn, turn_score = _turn_decision(src, corners, side)
    found_card = not np.allclose(corners, full_image(src.shape[1], src.shape[0]))
    reasons = review_reasons(src, corners, side, found_card, turn_score)
    too_small = abs(cv2.contourArea(np.asarray(corners, dtype=np.float32))) < FAIL_MIN_AREA * src.shape[0] * src.shape[1]
    if found_card and (_aspect_off(corners) or too_small):
        # T-262：抓到的框和身分證比例差很多、或小到不像整張卡片（多半只框到某一區塊，例如大頭照）：
        # 不硬裁，保留整張照片並提醒確認；照拍攝的方向顯示（不轉），免得整張照片被轉 90°。
        params = params_from_pixels(full_image(src.shape[1], src.shape[0]), 0, image.size, "full")
        params["needs_review"] = True
        return params
    if found_card:
        corners = expand_quad(corners, AUTO_MARGIN, src.shape[1], src.shape[0])
    else:
        # T-262 驗收：找不到卡片、自動改用整張照片時也照拍攝方向（不轉），訂單頁預覽、調整視窗、列印一致。
        # 整張照片的辨識本來就四個方向都試（id_ocr），不靠這個轉向。
        turn = 0
    params = params_from_pixels(corners, turn, image.size, "auto" if found_card else "full")
    params["needs_review"] = bool(reasons)
    return params


def _aspect_off(corners):
    width, height = _side_lengths(np.asarray(corners, dtype=np.float32))
    ratio = max(width, height) / max(1.0, min(width, height))
    return abs(math.log(ratio / CARD_ASPECT)) > FAIL_ASPECT_DEVIATION


def expand_quad(corners, margin, width, height):
    """四邊形以中心往外放大（每邊約 margin），並限制在照片範圍內。"""
    quad = np.asarray(corners, dtype=np.float32)
    center = quad.mean(axis=0)
    grown = center + (quad - center) * (1.0 + 2.0 * margin)
    grown[:, 0] = np.clip(grown[:, 0], 0, width - 1)
    grown[:, 1] = np.clip(grown[:, 1], 0, height - 1)
    return grown


def card_view(instance, model_name, field_name):
    """訂單頁附件、訂單明細顯示證件卡片用（T-199／T-200）：卡片網址、原圖網址、是否建議確認裁切。

    卡片網址就是原本受保護的 protected_media 加 ?card=1；c＝裁切參數摘要，參數改了瀏覽器就換一張。
    """
    import hashlib
    import json

    from django.urls import reverse

    file_field = getattr(instance, field_name)
    if not file_field:
        return None
    owner_type = instance.owner_type if model_name == "order" else (instance.data or {}).get("owner_type", "local")
    side = "front" if field_name == "id_front" else "back"
    original = reverse("protected_media", args=[model_name, instance.pk, field_name])
    try:
        params, _image = stored_or_auto_params(file_field, getattr(instance, CROP_FIELDS[field_name]),
                                               card_side_for(owner_type, side))
    except Exception:  # noqa: BLE001  讀不到照片：只給原圖。
        return {"url": original, "original_url": original, "needs_review": False, "name": Path(file_field.name).name}
    digest = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:10]
    return {
        "url": f"{original}?card=1&c={digest}",
        "original_url": original,
        "needs_review": bool(params.get("needs_review")),
        "name": f"{Path(file_field.name).stem}_card.jpg",
    }


def card_side_for(owner_type, side):
    """國民身分證依版面判斷上下；居留證（外籍）只轉成橫式。"""
    return side if owner_type == "local" else None


def stored_or_auto_params(file_field, saved, side=None, image=None):
    """畫面與列印用的裁切參數：訂單／草稿存的優先；沒有就自動偵測（結果放快取、不寫回資料庫）。

    回傳 (params, image)；image 只有在需要讀整張照片時才載入，否則為傳入值（可能是 None）。
    """
    from django.core.cache import cache

    size = image.size if image is not None else oriented_size(file_field)
    params = clean_params(saved, size) if size else None
    if params is not None:
        return params, image
    key = f"id-card-crop:v{CACHE_VERSION}:{side or 'any'}:{file_field.name}"
    cached = cache.get(key)
    if cached and size and (cached.get("src_w"), cached.get("src_h")) == tuple(size):
        return cached, image
    if image is None:
        with file_field.open("rb") as handle:
            image = open_oriented(handle.read())
    params = auto_params(image, side)
    cache.set(key, params, 60 * 60 * 24 * 7)
    return params, image


def apply_crop(image, params, width=CROP_WIDTH, height=CROP_HEIGHT):
    """依參數把原圖透視校正成卡片（預設 1012×638），再套用亮度與清晰度（T-220）。"""
    warped = warp(np.asarray(image), pixel_corners(params), params["turn"], width, height)
    return Image.fromarray(adjust(warped, params.get("brightness", 0), params.get("sharpness", 0)))


# ---------- 亮度／清晰度（C# ImageOps.AdjustMat，T-220） ----------

MIN_BRIGHTNESS, MAX_BRIGHTNESS, MAX_SHARPNESS = -50, 50, 100


def brightness_table(brightness):
    """L 通道的 gamma 查表：+50 → 中間調 128 變 172；-50 → 77。黑白兩端不動，調亮時白底不過曝。"""
    gamma = 2 ** (-brightness / 50.0 * 0.8)
    return np.array([min(max(round(255.0 * (i / 255.0) ** gamma), 0), 255) for i in range(256)], dtype=np.uint8)


def adjust(rgb, brightness=0, sharpness=0):
    """RGB 8 位元卡片圖套用亮度（LAB 的 L 通道 gamma）與清晰度（unsharp mask）；兩者都是 0 時原樣回傳。"""
    brightness = min(max(int(brightness or 0), MIN_BRIGHTNESS), MAX_BRIGHTNESS)
    sharpness = min(max(int(sharpness or 0), 0), MAX_SHARPNESS)
    out = rgb
    if brightness:
        lab = cv2.cvtColor(out, cv2.COLOR_RGB2LAB)
        lab[:, :, 0] = cv2.LUT(lab[:, :, 0], brightness_table(brightness))
        out = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    if sharpness:
        # 半徑依圖寬換算，縮小的預覽和 1012 px 的正式輸出看起來一致。
        sigma = max(0.5, 1.4 * out.shape[1] / CROP_WIDTH)
        amount = sharpness / 100.0 * 1.5
        blur = cv2.GaussianBlur(out, (0, 0), sigma)
        out = cv2.addWeighted(out, 1 + amount, blur, -amount, 0)
    return out


# ---------- 偵測四角（C# DetectCard） ----------

def _order(points):
    """順時針 左上、右上、右下、左下（影像座標 y 向下，角度遞增即順時針）。"""
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    center = points.mean(axis=0)
    angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
    ordered = points[np.argsort(angles, kind="stable")]
    sums = ordered[:, 0] + ordered[:, 1]
    start = 0
    for index in range(1, 4):
        if sums[index] < sums[start]:
            start = index
    return np.roll(ordered, -start, axis=0)


def _side_lengths(quad):
    def dist(a, b):
        return float(math.hypot(a[0] - b[0], a[1] - b[1]))
    return (dist(quad[0], quad[1]) + dist(quad[3], quad[2])) / 2, (dist(quad[0], quad[3]) + dist(quad[1], quad[2])) / 2


def _edge_skew(a, b, c, d):
    """兩條對邊（a→b 與 c→d，同方向）的夾角，單位度。"""
    first = math.atan2(float(b[1] - a[1]), float(b[0] - a[0]))
    second = math.atan2(float(d[1] - c[1]), float(d[0] - c[0]))
    diff = abs(math.degrees(first - second)) % 360
    return min(diff, 360 - diff)


def _aspect_score(quad):
    width, height = _side_lengths(quad)
    ratio = max(width, height) / max(1.0, min(width, height))
    return math.exp(-abs(math.log(ratio / CARD_ASPECT)) * 6)


def _int_points(quad, scale=1.0):
    # C# 以 (int) 轉型（向零截斷）。
    return np.trunc(np.asarray(quad, dtype=np.float64) * scale).astype(np.int32)


def full_image(width, height, inset=0.0):
    dx, dy = width * inset, height * inset
    return np.array(
        [[dx, dy], [width - 1 - dx, dy], [width - 1 - dx, height - 1 - dy], [dx, height - 1 - dy]],
        dtype=np.float32,
    )


def auto_turn(corners):
    """卡片是直拍的（高大於寬）就轉 90°，輸出維持橫式。"""
    width, height = _side_lengths(np.asarray(corners, dtype=np.float32))
    return 3 if height > width else 0


def detect_card(src):
    """找出照片中最像身分證的四邊形（原圖像素座標）；找不到時回傳整張。"""
    src_h, src_w = src.shape[:2]
    scale = min(1.0, 900.0 / max(src_w, src_h))
    small = cv2.resize(src, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else src
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    img_area = float(small.shape[0] * small.shape[1])
    state = {"best": None, "score": 0.0}
    candidates = []

    def consider(binary):
        contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            if cv2.contourArea(contour) < img_area * 0.01:
                continue
            hull = cv2.convexHull(contour)
            hull_area = cv2.contourArea(hull)
            if hull_area < img_area * 0.012 or hull_area > img_area * 0.97:
                continue
            perimeter = cv2.arcLength(hull, True)
            approx = cv2.approxPolyDP(hull, 0.02 * perimeter, True)
            if len(approx) == 4:
                quad, shape_factor = approx.reshape(4, 2).astype(np.float32), 1.0
            else:
                quad, shape_factor = cv2.boxPoints(cv2.minAreaRect(hull)).astype(np.float32), 0.7
            quad = _order(quad)
            quad_area = abs(cv2.contourArea(quad))
            if quad_area <= 0:
                continue
            fill = min(hull_area, quad_area) / max(hull_area, quad_area)
            if fill < 0.8:
                continue
            aspect = _aspect_score(quad)
            score = math.sqrt(quad_area / img_area) * aspect * fill * fill * shape_factor
            if score <= state["score"] * 0.3:
                continue  # 明顯不可能入選，省下量亮度的時間
            # 身分證正反面都是淺色底：框內越亮越像卡片，排除「卡片＋一大片深色桌面」這類錯框。
            mask = np.zeros(gray.shape, dtype=np.uint8)
            cv2.fillConvexPoly(mask, _int_points(quad), 255)
            inside = cv2.mean(gray, mask)[0] / 255.0
            score *= 0.3 + 0.7 * inside
            candidates.append((quad, score, aspect, quad_area))
            if score > state["score"]:
                state["score"], state["best"] = score, quad

    for low, high in ((30, 90), (50, 150), (80, 220), (15, 45)):
        edges = cv2.Canny(gray, low, high)
        edges = cv2.dilate(edges, _KERNEL, iterations=2)
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, _KERNEL, iterations=2)
        consider(edges)
    for kind in (cv2.THRESH_BINARY, cv2.THRESH_BINARY_INV):
        _, binary = cv2.threshold(gray, 0, 255, kind | cv2.THRESH_OTSU)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, _KERNEL, iterations=2)
        consider(binary)

    # 套在保護套、卡套裡的卡片：外框也是身分證比例且面積更大，常會勝出；
    # 最佳框內若還有一個像身分證、面積佔外框 50–92% 的框，就改用裡面那個。
    best = state["best"]
    while best is not None:
        outer_area = abs(cv2.contourArea(best))
        contour = best.reshape(-1, 1, 2)
        inner = [
            candidate for candidate in candidates
            if candidate[2] >= 0.5 and outer_area * 0.5 <= candidate[3] <= outer_area * 0.92
            and all(cv2.pointPolygonTest(contour, (float(x), float(y)), True) >= -3 for x, y in candidate[0])
        ]
        if not inner:
            break
        best = max(inner, key=lambda candidate: candidate[1])[0]

    # 已經裁好的卡片圖（整張就是身分證比例）：除非四邊形幾乎佔滿，否則直接用整張。
    img_ratio = max(src_w, src_h) / min(src_w, src_h)
    card_shaped = abs(math.log(img_ratio / CARD_ASPECT)) < 0.04
    best_fraction = 0.0 if best is None else abs(cv2.contourArea(best)) / img_area
    if best is None or (card_shaped and best_fraction < 0.6):
        return full_image(src_w, src_h)

    support = cv2.Canny(gray, 30, 90)
    support = cv2.dilate(support, _KERNEL)
    near_quad, near_score = _refine(best, support, gray, card_shaped, 0.04)
    far_quad, far_score = _refine(best, support, gray, card_shaped, 0.3)
    # 大幅微調多出來的區域若明顯比卡片暗（保護套、桌面），除非分數大幅領先，否則不採用。
    gained = _gained_brightness_ratio(gray, near_quad, far_quad)
    take_far = far_score > near_score * 1.4 or (far_score > near_score * 1.05 and gained >= 0.75)
    # T-262（使用者 2026-11-20 實拍：卡片幾乎填滿畫面時國旗與標題列被切掉）：大幅微調是用來把「只抓到一部分」的框補大，
    # 不可以把框往內縮——標題列下緣是一條又長又直的強邊，會把上緣整條拉進卡片裡。比微調前小就不採用。
    if take_far and abs(cv2.contourArea(np.asarray(far_quad, dtype=np.float32))) < abs(cv2.contourArea(np.asarray(near_quad, dtype=np.float32))) * 0.98:
        take_far = False
    if take_far:
        best = far_quad
    else:
        # 2.32.6（T-262 複驗回歸）：要不要採用大幅微調，照 2.32.4 用原本的近距結果判斷；補邊只在沒採用大幅微調時才做。
        # 先補邊再判斷，近距框變大會讓「多出來的區域」只剩深色標題列，正確的大幅微調反而不被採用（國旗被切掉）。
        best = _borrow_outer_edges(_keep_outer_edges(best, near_quad), far_quad, gray)
    return (np.asarray(best, dtype=np.float32) / scale).astype(np.float32)


INWARD_EDGE_TOLERANCE = 0.01


def _keep_outer_edges(initial, refined):
    """T-262 驗收：邊緣微調不可把任何一條邊（任一端）往卡片內部推超過對向邊長的 1%（例如背面條碼下緣、正面標題列下緣
    這種又長又直的強邊，會把整條邊吸進卡片裡，切掉角落）。超過就保留輪廓偵測原本的那條邊，四角取相鄰兩邊的交點。
    輪廓本身因膨脹多出的幾個像素在 1% 以內，照樣讓微調收緊。"""
    initial = np.asarray(_order(np.asarray(initial, dtype=np.float32)), dtype=np.float32)
    refined = np.asarray(_order(np.asarray(refined, dtype=np.float32)), dtype=np.float32)
    width, height = _side_lengths(initial)
    lines, changed = [], False
    for index in range(4):
        a, b = initial[index], initial[(index + 1) % 4]
        direction = b - a
        length = float(np.hypot(*direction))
        if length < 1e-6:
            return refined
        normal = np.array([direction[1], -direction[0]], dtype=np.float32) / length  # 角點順時針，這是朝外的法線
        p, q = refined[index], refined[(index + 1) % 4]
        # 兩端各自量：微調也可能只把一端往內拉（整條邊斜進卡片），角落一樣被切掉。
        inward = max(-float(np.dot(p - a, normal)), -float(np.dot(q - a, normal)))
        limit = INWARD_EDGE_TOLERANCE * (height if index % 2 == 0 else width)
        if inward > limit:
            lines.append((a, b))
            changed = True
        else:
            lines.append((p, q))
    if not changed:
        return refined
    corners = [_intersect(*lines[(index - 1) % 4], *lines[index]) for index in range(4)]
    if any(corner is None for corner in corners):
        return refined
    return np.asarray(corners, dtype=np.float32)


BORROW_EDGE_LIMIT = 0.05


def _borrow_outer_edges(near, far, gray):
    """T-262 驗收：沒採用大幅微調時，個別邊若大幅微調找到的位置在外側不遠（對向邊長 5% 內），且多出來那一條是亮的
    （還在淺色卡片上，不是證件套或桌面），就改用那一條邊。輪廓偵測有時整條邊斜進卡片（卡片幾乎填滿畫面時），
    角落會差幾十像素；這樣只補回那條邊，其他邊照近距微調。"""
    near = np.asarray(_order(np.asarray(near, dtype=np.float32)), dtype=np.float32)
    far = np.asarray(_order(np.asarray(far, dtype=np.float32)), dtype=np.float32)
    width, height = _side_lengths(near)
    near_mask = np.zeros(gray.shape, dtype=np.uint8)
    cv2.fillConvexPoly(near_mask, _int_points(near), 255)
    near_mean = cv2.mean(gray, near_mask)[0]
    lines, changed = [], False
    for index in range(4):
        a, b = near[index], near[(index + 1) % 4]
        direction = b - a
        length = float(np.hypot(*direction))
        p, q = far[index], far[(index + 1) % 4]
        if length >= 1e-6 and near_mean >= 1:
            normal = np.array([direction[1], -direction[0]], dtype=np.float32) / length
            outward = (float(np.dot(p - a, normal)), float(np.dot(q - a, normal)))
            limit = BORROW_EDGE_LIMIT * (height if index % 2 == 0 else width)
            if min(outward) > 0 and max(outward) <= limit:
                strip = np.zeros(gray.shape, dtype=np.uint8)
                cv2.fillConvexPoly(strip, _int_points(np.array([a, b, q, p], dtype=np.float32)), 255)
                if cv2.countNonZero(strip) and cv2.mean(gray, strip)[0] >= near_mean * 0.75:
                    lines.append((p, q))
                    changed = True
                    continue
        lines.append((a, b))
    if not changed:
        return near
    corners = [_intersect(*lines[(index - 1) % 4], *lines[index]) for index in range(4)]
    if any(corner is None for corner in corners):
        return near
    return np.asarray(corners, dtype=np.float32)


def _between(values, target):
    if target > 0:
        return (values > 6) & (values < target - 6)
    return (values < -6) & (values > target + 6)


def _side_options(a, b, normal, shifts, edge_mask, border_is_edge):
    """一條邊兩端各自沿法線平移的所有組合中，邊緣支持度高的前 5 名（含原位置）。"""
    height, width = edge_mask.shape
    t = (0.08 + 0.84 * np.arange(64) / 63).astype(np.float32)
    base = a[None, :] * (1 - t)[:, None] + b[None, :] * t[:, None]  # (64, 2)
    d1, d2 = np.meshgrid(shifts, shifts, indexing="ij")
    offset = d1[..., None] * (1 - t) + d2[..., None] * t  # (S, S, 64)
    xs = np.trunc(base[:, 0] + normal[0] * offset + 0.5).astype(np.int32)
    ys = np.trunc(base[:, 1] + normal[1] * offset + 0.5).astype(np.int32)
    inside = (xs >= 0) & (ys >= 0) & (xs < width) & (ys < height)
    hit = np.zeros(xs.shape, dtype=np.float32)
    hit[inside] = edge_mask[ys[inside], xs[inside]]
    if border_is_edge:
        # 已裁好的圖：卡片邊緣就是圖片邊界，算成較弱的邊緣，真的看得到邊線時以邊線優先。
        border = inside & (hit == 0) & ((xs <= 1) | (ys <= 1) | (xs >= width - 2) | (ys >= height - 2))
        hit[border] = 0.9
    support = hit.sum(axis=-1) / 64.0

    flat_d1, flat_d2, flat_s = d1.ravel(), d2.ravel(), support.ravel()
    origin = (flat_d1 == 0) & (flat_d2 == 0)
    keep = (flat_s >= 0.5) | origin
    found_d1, found_d2, found_s = flat_d1[keep], flat_d2[keep], flat_s[keep]
    strong = found_s >= 0.6
    strong_d1, strong_d2 = found_d1[strong], found_d2[strong]

    picked = []
    for index in np.argsort(-found_s, kind="stable"):
        p1, p2, score = int(found_d1[index]), int(found_d2[index]), float(found_s[index])
        if any(abs(q1 - p1) <= 6 and abs(q2 - p2) <= 6 for q1, q2, _ in picked):
            continue
        # 中間隔著另一條完整直線的位置不採用：那代表越過保護套、卡套或桌面上的其他邊。
        if (p1 or p2) and np.any(_between(strong_d1, p1) & _between(strong_d2, p2)):
            continue
        picked.append((p1, p2, score))
        if len(picked) == 5:
            break
    if not any(p1 == 0 and p2 == 0 for p1, p2, _ in picked):
        picked.append((0, 0, float(flat_s[origin][0])))
    return [(a + normal * p1, b + normal * p2, score) for p1, p2, score in picked]


def _intersect(p1, p2, p3, p4):
    d = (p1[0] - p2[0]) * (p3[1] - p4[1]) - (p1[1] - p2[1]) * (p3[0] - p4[0])
    if abs(d) < 1e-6:
        return None
    t = ((p1[0] - p3[0]) * (p3[1] - p4[1]) - (p1[1] - p3[1]) * (p3[0] - p4[0])) / d
    return np.array([p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1])], dtype=np.float32)


def _mean_inside(image, quad, scale):
    mask = np.zeros(image.shape, dtype=np.uint8)
    cv2.fillConvexPoly(mask, _int_points(quad, scale), 255)
    return cv2.mean(image, mask)[0] / 255.0


def _refine(quad, edges, gray, border_is_edge, max_shift):
    """卡片邊緣貼著雜物或內部有色帶時，輪廓常只抓到一部分：四邊各自沿法線平移找支持度高的直線，再挑最像身分證的組合。"""
    height, width = edges.shape
    tiny = cv2.resize(gray, (0, 0), fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    edge_mask = (edges != 0).astype(np.float32)
    quad = np.asarray(quad, dtype=np.float32)
    center = quad.mean(axis=0)
    options = []
    for index in range(4):
        a, b = quad[index], quad[(index + 1) % 4]
        opposite_mid = (quad[(index + 2) % 4] + quad[(index + 3) % 4]) / 2
        mid = (a + b) / 2
        length = float(np.hypot(*(b - a)))
        if length < 1:
            return quad, 0.0
        direction = (b - a) / length
        normal = np.array([direction[1], -direction[0]], dtype=np.float32)
        if float(np.dot(mid - center, normal)) < 0:
            normal = -normal
        step = 2
        shift_range = max(4, int(float(np.hypot(*(mid - opposite_mid))) * max_shift))
        shift_range -= shift_range % step  # 確保 d = 0（原位置）一定會被評估
        shifts = np.arange(-shift_range, shift_range + 1, step, dtype=np.float32)
        options.append(_side_options(a, b, normal, shifts, edge_mask, border_is_edge))

    best_quad, best_score, img_area = quad, -1.0, float(width * height)
    for s0 in options[0]:
        for s1 in options[1]:
            for s2 in options[2]:
                for s3 in options[3]:
                    sides = (s0, s1, s2, s3)
                    corners = []
                    for index in range(4):
                        previous = sides[(index + 3) % 4]
                        point = _intersect(previous[0], previous[1], sides[index][0], sides[index][1])
                        if point is None or not (-5 < point[0] < width + 5 and -5 < point[1] < height + 5):
                            break
                        corners.append(point)
                    if len(corners) != 4:
                        continue
                    candidate = np.array(corners, dtype=np.float32)
                    if not cv2.isContourConvex(_int_points(candidate)):
                        continue
                    support = sum(side[2] for side in sides) / 4
                    area = abs(cv2.contourArea(candidate))
                    score = (
                        _aspect_score(candidate) * support * support * (area / img_area) ** 0.25
                        * (0.3 + 0.7 * _mean_inside(tiny, candidate, 0.25))
                    )
                    if score > best_score:
                        best_score, best_quad = score, candidate
    return best_quad, best_score


def _gained_brightness_ratio(gray, near, far):
    near_mask = np.zeros(gray.shape, dtype=np.uint8)
    cv2.fillConvexPoly(near_mask, _int_points(near), 255)
    gain_mask = np.zeros(gray.shape, dtype=np.uint8)
    cv2.fillConvexPoly(gain_mask, _int_points(far), 255)
    cv2.fillConvexPoly(gain_mask, _int_points(near), 0)
    if cv2.countNonZero(gain_mask) < abs(cv2.contourArea(np.asarray(far, dtype=np.float32))) * 0.02:
        return 1.0
    near_mean = cv2.mean(gray, near_mask)[0]
    return 1.0 if near_mean < 1 else cv2.mean(gray, gain_mask)[0] / near_mean


# ---------- 透視校正（C# Warp） ----------

def warp(src, corners, turn, width=CROP_WIDTH, height=CROP_HEIGHT, high_quality=True):
    corners = np.asarray(corners, dtype=np.float32)
    quad = np.array([corners[(index + turn) % 4] for index in range(4)], dtype=np.float32)
    factor = 2 if high_quality else 1
    out_w, out_h = width * factor, height * factor
    target = np.array([[0, 0], [out_w, 0], [out_w, out_h], [0, out_h]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(quad, target)
    warped = cv2.warpPerspective(src, matrix, (out_w, out_h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    if factor == 1:
        return warped
    return cv2.resize(warped, (width, height), interpolation=cv2.INTER_AREA)


# ---------- 判斷上下（C# DetectTurn） ----------

def _gray_card(card):
    gray = cv2.cvtColor(card, cv2.COLOR_RGB2GRAY)
    if gray.shape != (202, 320):
        gray = cv2.resize(gray, (320, 202), interpolation=cv2.INTER_AREA)
    return gray


def _region(image, x0, y0, x1, y1):
    x, y = int(x0 * 320), int(y0 * 202)
    return image[y:y + int((y1 - y0) * 202), x:x + int((x1 - x0) * 320)]


def front_upright_score(card):
    """正值＝正面朝上：大頭照區（右）比左側對稱區暗。"""
    gray = _gray_card(card)
    return float(_region(gray, 0.04, 0.16, 0.30, 0.80).mean() - _region(gray, 0.70, 0.20, 0.96, 0.84).mean())


def back_upright_score(card):
    """正值＝反面朝上：左下條碼區的水平梯度比右上對稱區密。"""
    gradient = np.abs(cv2.Sobel(_gray_card(card), cv2.CV_32F, 1, 0))
    return float(_region(gradient, 0.04, 0.70, 0.62, 0.93).mean() - _region(gradient, 0.38, 0.07, 0.96, 0.30).mean())


def _turn_decision(src, corners, side=None):
    """回傳 (turn, (分數, 用哪一面的特徵))；居留證或無法判斷時分數為 None。"""
    turn = auto_turn(corners)
    if side not in ("front", "back"):
        return turn, None
    try:
        card = warp(src, corners, turn, 320, 202, high_quality=False)
    except cv2.error:
        return turn, None
    # 條碼特徵很強（反面 ≥ 50、正面 ≤ 25）：有條碼就當反面判斷，正反面放錯格也能轉對。
    back = back_upright_score(card)
    used = "back" if side == "back" or abs(back) >= 35 else "front"
    score = back if used == "back" else front_upright_score(card)
    return ((turn + 2) % 4 if score < 0 else turn), (score, used)


def detect_turn(src, corners, side=None):
    """先維持橫式，再依國民身分證固定版面判斷是否上下顛倒。

    side：front／back 用國民身分證版面；None（居留證）只轉成橫式，上下交給 OCR 判斷。
    """
    return _turn_decision(src, corners, side)[0]
