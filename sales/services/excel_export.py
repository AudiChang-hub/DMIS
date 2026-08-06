"""Excel 匯出的共用安全處理。"""

from collections.abc import Iterable
from typing import Any


EXCEL_FORMULA_PREFIXES = ("=", "+", "-", "@")


def sanitize_excel_value(value: Any) -> Any:
    """避免使用者文字被試算表軟體當成公式執行。

    數字、日期等原生型別維持不變；可疑文字前置單引號，讓 Excel
    以純文字儲存。換行或 tab 開頭也一併檢查，避免繞過首字元判斷。
    """

    if not isinstance(value, str):
        return value

    candidate = value.lstrip("\t\r\n")
    if candidate.startswith(EXCEL_FORMULA_PREFIXES):
        return f"'{value}"
    return value


def sanitize_excel_row(values: Iterable[Any]) -> list[Any]:
    """回傳可安全寫入 Excel 的一列資料。"""

    return [sanitize_excel_value(value) for value in values]
