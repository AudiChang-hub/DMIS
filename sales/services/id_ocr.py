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
    return texts[0].description if texts else ""


def recognize_side(image_bytes, expected_side, client=None):
    if expected_side not in {"front", "back"}:
        raise ValueError("expected_side 必須是 front 或 back")
    image = _load_image(image_bytes)
    client = client or _vision_client()
    keywords = (
        ("中華民國", "姓名", "統一編號")
        if expected_side == "front"
        else ("住址", "出生地", "父", "母")
    )
    first_text = ""
    for angle in (0, 90, 180, 270):
        rotated = image if angle == 0 else image.rotate(angle, expand=True)
        text = _detect_text(client, rotated)
        if angle == 0:
            first_text = text
        if any(keyword in text for keyword in keywords):
            return OcrImageResult(expected_side, angle, text)
    return OcrImageResult(expected_side, 0, first_text)


def extract_fields(text, side):
    result = {}
    normalized = text.replace("臺", "台")
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    if side == "front":
        name_block = re.search(r"姓名(.*?)(?:出生|性別)", normalized, re.DOTALL)
        if name_block:
            name = re.sub(r"[^\u4e00-\u9fff]", "", name_block.group(1))
            name = re.sub(r"(中華民國國民身分證|國民身分證)", "", name)
            if 2 <= len(name) <= 6:
                result["name"] = name
        birth = re.search(
            r"民國\s*(\d{1,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
            normalized,
        )
        if birth:
            roc_year, month, day = map(int, birth.groups())
            try:
                result["birth_date"] = date(
                    roc_year + 1911, month, day
                ).isoformat()
            except ValueError:
                pass
        id_match = re.search(r"\b[A-Z][12]\d{8}\b", normalized.upper())
        if id_match:
            result["id_number"] = id_match.group(0)
            result["id_number_valid"] = validate_taiwan_id(result["id_number"])
    elif side == "back":
        address_lines = []
        collecting = False
        stop_words = ("父", "母", "配偶", "役別", "出生地")
        for line in lines:
            cleaned = re.sub(r"\s+", "", line).replace("住址", "")
            if "住址" in line or (
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
    fields = extract_fields(front.text, "front")
    fields.update(extract_fields(back.text, "back"))
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
