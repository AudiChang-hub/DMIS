"""車主證件號碼格式檢查（UAT U-05，使用者 2026-11-03 選 A）。

客戶依證件號碼歸戶，打錯一碼就會變成兩位客戶：本國自然人檢查身分證格式與檢查碼，錯了就擋；
法人只檢查統一編號 8 碼數字；外籍／居留者可能用居留證或護照，只檢查英數與長度。
畫面即時提示（_order_form_scripts.html）用同一套規則，以這裡為準。
"""
import re

TAIWAN_ID_PATTERN = re.compile(r"[A-Z][12]\d{8}")
# 身分證第一碼英文字母對應的縣市代碼。
CITY_CODES = {
    "A": 10, "B": 11, "C": 12, "D": 13, "E": 14, "F": 15,
    "G": 16, "H": 17, "I": 34, "J": 18, "K": 19, "L": 20,
    "M": 21, "N": 22, "O": 35, "P": 23, "Q": 24, "R": 25,
    "S": 26, "T": 27, "U": 28, "V": 29, "W": 32, "X": 30,
    "Y": 31, "Z": 33,
}
FOREIGN_ID_PATTERN = re.compile(r"[A-Z0-9]{6,20}")
COMPANY_ID_PATTERN = re.compile(r"\d{8}")


def validate_taiwan_id(id_number):
    value = (id_number or "").strip().upper()
    if not TAIWAN_ID_PATTERN.fullmatch(value):
        return False
    code = CITY_CODES[value[0]]
    digits = [int(char) for char in value[1:]]
    total = code // 10 + (code % 10) * 9
    total += sum(digit * weight for digit, weight in zip(digits[:8], range(8, 0, -1)))
    total += digits[8]
    return total % 10 == 0


def owner_id_number_problem(owner_type, id_number):
    """回傳白話的錯誤說明；沒問題回傳空字串。證號選填（2026-11-13 T-156），空白不檢查。"""
    value = (id_number or "").strip().upper()
    if not value:
        return ""
    if owner_type == "company":
        if COMPANY_ID_PATTERN.fullmatch(value):
            return ""
        return "統一編號要 8 個數字，請對照公司資料重新輸入。如果車主是個人，請先把上方「車主類型」改掉。"
    if owner_type == "foreign":
        if FOREIGN_ID_PATTERN.fullmatch(value):
            return ""
        return "證件號碼只能有英文字母和數字，長度 6 到 20 碼，請對照居留證或護照重新輸入。"
    if not TAIWAN_ID_PATTERN.fullmatch(value):
        return ("身分證字號格式不對：共 10 碼，第 1 碼是英文字母、第 2 碼是 1 或 2，後面 8 個數字。"
                "請對照證件重新輸入；外籍或公司請先把上方「車主類型」改掉。")
    if not validate_taiwan_id(value):
        return "身分證字號的檢查碼對不上，應該有一碼打錯了，請對照證件逐碼重新輸入。"
    return ""
