"""Excel 進貨 M 欄（存放／調車）判讀。

M 欄沒有表頭，記錄車放在哪間車行與調車、領車資訊（使用者 2026-10-10 說明）：
- 只寫車行名稱（「昌勝」）＝車放在那間車行；可帶括號備註（「昌勝(已配電)」）。
- 「XX調走」「XX調」「MM/DD XX調」＝調給 XX（調出）；「調回工廠」等調給非車行也算調出。
- 「XX領」「MM/DD XX領」＝車行來把車領走（已交給車行）。
- 「馭盛」「公司」＝本店；其他文字（「員購車」「無電瓶」）當備註。
日期只有月／日時，以進貨日期推年份（早於進貨日則視為隔年）。
"""
import re
from datetime import date

STORE_WORDS = {"馭盛", "公司", "本店", "總店"}
DATE_PREFIX = re.compile(r"^\s*(?P<month>\d{1,2})\s*/\s*(?P<day>\d{1,2})\s*")
PAREN = re.compile(r"^(?P<name>[^()（）]+)[（(](?P<note>[^()（）]*)[)）]$")
LOCATION, TRANSFER_OUT, DEALER_PICKUP, NOTE = "location", "transfer_out", "dealer_pickup", "note"


def _infer_date(month, day, received_on):
    year = received_on.year if received_on else date.today().year
    try:
        result = date(year, month, day)
    except ValueError:
        return None
    if received_on and result < received_on:
        try:
            result = date(year + 1, month, day)
        except ValueError:
            return None
    return result


def parse(text, received_on=None):
    """回傳 dict：kind（location／transfer_out／dealer_pickup／note）、name（車行或對象原文）、
    on（日期或 None）、note（附註）、store（是否為本店）、raw（原文）。"""
    raw = " ".join(str(text or "").split())
    result = {"kind": "", "name": "", "on": None, "note": "", "store": False, "raw": raw}
    if not raw:
        return result
    rest = raw
    match = DATE_PREFIX.match(rest)
    if match:
        result["on"] = _infer_date(int(match["month"]), int(match["day"]), received_on)
        rest = rest[match.end():].strip()
    if "調" in rest:
        before, _sep, after = rest.partition("調")
        name = before.strip().removesuffix("已").strip()
        if not name and after.startswith("回"):
            name = after[1:].removesuffix("走").removesuffix("已載走").strip()  # 「調回工廠」
        result.update(kind=TRANSFER_OUT, name=name)
        extra = after.removeprefix("回").removeprefix("走").strip() if before.strip() else ""
        if extra and extra not in {"已載走", "載走"}:
            result["note"] = extra
        return result
    if rest.endswith("領"):
        name = rest[:-1].strip()
        if name in STORE_WORDS:  # 「馭盛領」＝本店領回，不是車行領車
            result.update(kind=LOCATION, name=name, store=True, note=raw)
        else:
            result.update(kind=DEALER_PICKUP, name=name)
        return result
    if "載走" in rest:
        name = rest.split("載走")[0].removesuffix("已").strip()
        result.update(kind=LOCATION, name=name, store=name in STORE_WORDS, note=raw)
        return result
    paren = PAREN.match(rest)
    name, note = (paren["name"].strip(), paren["note"].strip()) if paren else (rest, "")
    result.update(kind=LOCATION, name=name, note=note, store=name in STORE_WORDS)
    return result
