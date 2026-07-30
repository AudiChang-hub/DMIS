import io
import os
import re
from dataclasses import dataclass
from datetime import date

from google.api_core.retry import Retry
from google.cloud import vision
from google.oauth2 import service_account
from PIL import Image, ImageOps, UnidentifiedImageError


MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 24_000_000
OCR_TIMEOUT_SECONDS = 20
OCR_RETRY = Retry(
    initial=1.0,
    maximum=4.0,
    multiplier=2.0,
    deadline=30.0,
)


class IdOcrError(Exception):
    """可安全顯示給使用者的 OCR 錯誤。"""


@dataclass(frozen=True)
class OcrImageResult:
    side: str
    angle: int
    text: str
    annotations: tuple
    image: Image.Image


def _vision_client():
    credential_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not credential_path or not os.path.isfile(credential_path):
        raise IdOcrError("OCR 服務尚未設定，請聯絡管理者。")
    credentials = service_account.Credentials.from_service_account_file(
        credential_path
    )
    return vision.ImageAnnotatorClient(credentials=credentials)


def _load_image(image_bytes):
    if not image_bytes:
        raise IdOcrError("未收到證件照片。")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise IdOcrError("單張照片不可超過 10 MB。")
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.verify()
        image = Image.open(io.BytesIO(image_bytes))
        image = ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise IdOcrError("檔案不是可辨識的照片。") from exc
    if image.width * image.height > MAX_IMAGE_PIXELS:
        raise IdOcrError("照片解析度過大，請降低解析度後重試。")
    return image


def _image_as_jpeg(image):
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=92, optimize=True)
    return output.getvalue()


def _detect_text(client, image):
    response = client.text_detection(
        image=vision.Image(content=_image_as_jpeg(image)),
        timeout=OCR_TIMEOUT_SECONDS,
        retry=OCR_RETRY,
    )
    if response.error.message:
        raise IdOcrError("OCR 服務暫時無法辨識，請稍後再試。")
    texts = response.text_annotations
    return (texts[0].description if texts else ""), tuple(texts[1:])


def _side_scores(text):
    normalized = re.sub(r"\s+", "", text.replace("臺", "台")).upper()
    front_score = 0
    back_score = 0
    if "中華民國國民身分證" in normalized:
        front_score += 6
    elif "國民身分證" in normalized:
        front_score += 4
    if "姓名" in normalized:
        front_score += 2
    if "出生年月日" in normalized:
        front_score += 2
    if re.search(r"[A-Z][12]\d{8}", normalized):
        front_score += 4

    for marker, score in (
        ("住址", 3),
        ("出生地", 2),
        ("配偶", 1),
        ("役別", 1),
    ):
        if marker in normalized:
            back_score += score
    if "父" in normalized:
        back_score += 1
    if "母" in normalized:
        back_score += 1
    # 反面右下識別圖樣旁有10位數綠色流水號；正面的身分證字號
    # 則一定以英文字母開頭，因此不會互相混淆。
    if re.search(r"(?<!\d)\d{10}(?!\d)", normalized):
        back_score += 5
    return {"front": front_score, "back": back_score}


def detect_id_side(text):
    scores = _side_scores(text)
    if scores["front"] >= 4 and scores["front"] >= scores["back"] + 2:
        return "front"
    if scores["back"] >= 4 and scores["back"] >= scores["front"] + 2:
        return "back"
    return "unknown"


def recognize_side(image_bytes, expected_side, client=None):
    if expected_side not in {"front", "back"}:
        raise ValueError("expected_side 必須是 front 或 back")
    image = _load_image(image_bytes)
    client = client or _vision_client()
    best_result = None
    best_score = -1
    for angle in (0, 90, 180, 270):
        rotated = image if angle == 0 else image.rotate(angle, expand=True)
        text, annotations = _detect_text(client, rotated)
        score = _side_scores(text)[expected_side]
        if score > best_score:
            best_score = score
            best_result = OcrImageResult(
                expected_side, angle, text, annotations, rotated
            )
        # 強特徵已足以判斷方向，不再做其餘三次外部 OCR。
        if score >= 4:
            return OcrImageResult(
                expected_side, angle, text, annotations, rotated
            )
    return best_result


def _clean_name_text(text):
    normalized = text.replace("臺", "台")
    if "姓名" in normalized:
        normalized = normalized.split("姓名", 1)[1]
    name = re.sub(r"[^\u4e00-\u9fff]", "", normalized)
    name = re.sub(
        r"(中華民國國民身分證|國民身分證|身分證統一編號|"
        r"統一編號|姓名|性別|出生|民國|年月日|男|女)",
        "",
        name,
    )
    return name if 2 <= len(name) <= 6 else ""


def _recognize_name_region(client, front):
    label = next(
        (
            annotation
            for annotation in front.annotations
            if "姓名" in annotation.description
        ),
        None,
    )
    width, height = front.image.size
    crop_boxes = []
    if label and label.bounding_poly.vertices:
        vertices = label.bounding_poly.vertices
        xs = [vertex.x for vertex in vertices]
        ys = [vertex.y for vertex in vertices]
        # 姓名位於標籤右側同一列。避免舊範圍向下吃到生日、性別等文字，
        # 也把右界放寬，保留字距較大的第三或第四個姓名字元。
        crop_boxes.append(
            (
                max(0, max(xs) - int(width * 0.01)),
                max(0, min(ys) - int(height * 0.05)),
                min(width, max(xs) + int(width * 0.52)),
                min(height, max(ys) + int(height * 0.12)),
            )
        )
    # 部分照片中 Vision 會把「姓」「名」拆開而找不到完整標籤。
    # 台灣身分證正面姓名區約位於畫面左中段，作為位置式備援。
    crop_boxes.append(
        (
            int(width * 0.16),
            int(height * 0.34),
            int(width * 0.68),
            int(height * 0.64),
        )
    )
    candidates = []
    for index, crop_box in enumerate(crop_boxes):
        if crop_box[2] <= crop_box[0] or crop_box[3] <= crop_box[1]:
            continue
        text, _ = _detect_text(client, front.image.crop(crop_box))
        candidate = _clean_name_text(text)
        if candidate:
            candidates.append(candidate)
        # 標籤裁切已取得常見的三至六字姓名，不必增加一次外部 OCR 呼叫。
        if index == 0 and len(candidate) >= 3:
            break
    return max(candidates, key=len, default="")


_ID_DIGIT_CORRECTIONS = str.maketrans(
    {"O": "0", "D": "0", "Q": "0", "I": "1", "L": "1", "Z": "2",
     "S": "5", "G": "6", "B": "8"}
)


def _extract_id_number(text):
    compact = re.sub(r"[\s\-‐‑–—]", "", text.upper())
    candidates = re.findall(r"[A-Z][12][0-9A-Z]{8}", compact)
    first_candidate = ""
    for candidate in candidates:
        normalized = candidate[:2] + candidate[2:].translate(_ID_DIGIT_CORRECTIONS)
        if not re.fullmatch(r"[A-Z][12]\d{8}", normalized):
            continue
        first_candidate = first_candidate or normalized
        if validate_taiwan_id(normalized):
            return normalized
    return first_candidate


def _extract_birth_date(text):
    patterns = (
        # 優先鎖定出生欄，避免抓到同一面的發證日期。
        r"出生(?:\s*年\s*月\s*日)?[\s:：]*民國\s*(\d{1,3})\s*年"
        r"\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
        r"民國\s*(\d{1,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
    )
    current_roc_year = date.today().year - 1911
    for pattern_index, pattern in enumerate(patterns):
        for match in re.finditer(pattern, text):
            roc_year, month, day = map(int, match.groups())
            # 非出生欄的備援日期需排除近期發證日期。
            if pattern_index and not 14 <= current_roc_year - roc_year <= 120:
                continue
            try:
                return date(roc_year + 1911, month, day).isoformat()
            except ValueError:
                continue
    return ""


def _choose_name_candidate(full_name, region_name):
    full_name = (full_name or "").strip()
    region_name = (region_name or "").strip()
    if not full_name:
        return region_name
    if not region_name or region_name == full_name:
        return full_name
    # 常見漏字情境是整張 OCR 只取得前兩字，而姓名列局部 OCR 多取得
    # 同一前綴後的一字。限制只能補一字，避免把底紋或鄰近欄位誤認字
    # 加到原本已完整的三、四字姓名後方。
    if (
        len(full_name) == 2
        and len(region_name) == 3
        and region_name.startswith(full_name)
    ):
        return region_name
    return full_name


def extract_fields(text, side):
    result = {}
    normalized = text.replace("臺", "台")
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    if side == "front":
        # 姓名為直排，Vision 有時會把最後一字排到「性別」標籤後方。
        name_block = re.search(r"姓名(.*?)出生", normalized, re.DOTALL)
        if name_block:
            name = _clean_name_text(name_block.group(1))
            if name:
                result["name"] = name
        birth_date = _extract_birth_date(normalized)
        if birth_date:
            result["birth_date"] = birth_date
        id_number = _extract_id_number(normalized)
        if id_number:
            result["id_number"] = id_number
            result["id_number_valid"] = validate_taiwan_id(result["id_number"])
    elif side == "back":
        address_lines = []
        collecting = False
        stop_words = ("父", "母", "配偶", "役別", "出生地")
        for line in lines:
            compact_line = re.sub(r"\s+", "", line)
            cleaned = compact_line.replace("住址", "")
            if "住址" in compact_line or (
                not collecting
                and re.search(r"[縣市].*[區鄉鎮市]", cleaned)
            ):
                collecting = True
            if collecting:
                if any(cleaned.startswith(word) for word in stop_words):
                    break
                address_lines.append(cleaned)
                if re.search(r"(號|樓|樓之\d+)$", cleaned):
                    break
        address = "".join(address_lines)
        address = re.sub(r"[A-Za-z\s]", "", address)
        if address:
            result["address"] = address
    return result


def validate_taiwan_id(id_number):
    value = (id_number or "").strip().upper()
    if not re.fullmatch(r"[A-Z][12]\d{8}", value):
        return False
    city_codes = {
        "A": 10, "B": 11, "C": 12, "D": 13, "E": 14, "F": 15,
        "G": 16, "H": 17, "I": 34, "J": 18, "K": 19, "L": 20,
        "M": 21, "N": 22, "O": 35, "P": 23, "Q": 24, "R": 25,
        "S": 26, "T": 27, "U": 28, "V": 29, "W": 32, "X": 30,
        "Y": 31, "Z": 33,
    }
    code = city_codes[value[0]]
    digits = [int(char) for char in value[1:]]
    total = code // 10 + (code % 10) * 9
    total += sum(digit * weight for digit, weight in zip(digits[:8], range(8, 0, -1)))
    total += digits[8]
    return total % 10 == 0


def recognize_id_card(front_bytes, back_bytes):
    client = _vision_client()
    front = recognize_side(front_bytes, "front", client)
    back = recognize_side(back_bytes, "back", client)
    detected_front = detect_id_side(front.text)
    detected_back = detect_id_side(back.text)
    if detected_front == "back" and detected_back == "front":
        raise IdOcrError("證件正反面似乎放反，請交換照片後重新辨識。")
    if detected_front == detected_back == "front":
        raise IdOcrError("兩張照片看起來都是證件正面，請重新拍攝反面。")
    if detected_front == detected_back == "back":
        raise IdOcrError("兩張照片看起來都是證件反面，請重新拍攝正面。")
    fields = extract_fields(front.text, "front")
    fields.update(extract_fields(back.text, "back"))
    region_name = _recognize_name_region(client, front)
    chosen_name = _choose_name_candidate(fields.get("name"), region_name)
    if chosen_name:
        fields["name"] = chosen_name
    warnings = []
    required = {
        "name": "姓名",
        "birth_date": "生日",
        "id_number": "身分證字號",
        "address": "戶籍地址",
    }
    missing = [label for key, label in required.items() if not fields.get(key)]
    if missing:
        warnings.append(f"未辨識：{'、'.join(missing)}，請人工輸入。")
    if fields.get("id_number") and not fields.get("id_number_valid"):
        warnings.append("身分證字號檢核未通過，請對照照片修正。")
    return {
        "fields": fields,
        "warnings": warnings,
        "rotation": {"front": front.angle, "back": back.angle},
    }
