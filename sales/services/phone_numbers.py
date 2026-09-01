import re


TAIWAN_CITY_AREA_CODES = {
    "臺北市": "02",
    "新北市": "02",
    "基隆市": "02",
    "桃園市": "03",
    "新竹市": "03",
    "新竹縣": "03",
    "宜蘭縣": "03",
    "花蓮縣": "03",
    "苗栗縣": "037",
    "臺中市": "04",
    "彰化縣": "04",
    "南投縣": "049",
    "雲林縣": "05",
    "嘉義市": "05",
    "嘉義縣": "05",
    "臺南市": "06",
    "澎湖縣": "06",
    "高雄市": "07",
    "屏東縣": "08",
    "臺東縣": "089",
    "金門縣": "082",
    "連江縣": "0836",
}


def format_taiwan_phone(value, city=""):
    """回傳可閱讀且可直接放入 tel: 的臺灣電話號碼。"""
    raw = (value or "").strip()
    if not raw:
        return ""
    main_number = re.split(r"(?:分機|ext\.?|#)", raw, maxsplit=1, flags=re.IGNORECASE)[0]
    digits = re.sub(r"\D", "", main_number)
    if digits.startswith("886"):
        digits = "0" + digits[3:]
    if not digits:
        return ""

    if digits.startswith("09") and len(digits) == 10:
        return f"{digits[:4]}-{digits[4:7]}-{digits[7:]}"

    normalized_city = (city or "").strip().replace("台", "臺")
    area_code = TAIWAN_CITY_AREA_CODES.get(normalized_city, "")
    if not digits.startswith("0") and area_code and len(digits) in {7, 8}:
        digits = area_code + digits
    if area_code and digits.startswith(area_code) and len(digits) > len(area_code):
        return f"{area_code}-{digits[len(area_code):]}"
    return digits
