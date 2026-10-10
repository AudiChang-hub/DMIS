"""Excel 進貨 M 欄（存放／調車）判讀。

M 欄沒有表頭，記錄車放在哪間車行與調車、領車資訊（使用者 2026-10-10 說明）：
- 只寫車行名稱（「昌勝」）＝車放在那間車行；可帶括號備註（「昌勝(已配電)」）。
- 「XX調走」「XX調」「MM/DD XX調」＝調給 XX（調出）；「調回工廠」等調給非車行也算調出。
- 「XX領」「MM/DD XX領」＝車行來把車領走（已交給車行）。
- 「馭盛」「公司」＝本店；其他文字（「員購車」「無電瓶」）當備註。
日期只有月／日時，以進貨日期推年份（早於進貨日則視為隔年）。
M 欄之後無表頭的 N～P 欄也會寫後續動向（例如 M「旭昶」、N「6/23榮擎調走」），由 resolve() 合併判讀。
"""
import re
from datetime import date

STORE_WORDS = {"馭盛", "公司", "本店", "總店"}
# 「調回工廠」等：原廠或總公司把車調回去（使用者 2026-10-10 確認「公司調走」即此意），統一記為同一個名稱。
FACTORY_WORDS = {"工廠", "原廠", "總公司", "原廠／總公司"}
FACTORY_LABEL = "原廠／總公司"
DATE_PREFIX = re.compile(r"^\s*(?P<month>\d{1,2})\s*/\s*(?P<day>\d{1,2})\s*")
PAREN = re.compile(r"^(?P<name>[^()（）]+)[（(](?P<note>[^()（）]*)[)）]$")
LOCATION, TRANSFER_OUT, DEALER_PICKUP, NOTE = "location", "transfer_out", "dealer_pickup", "note"
IDENTIFIER = re.compile(r"^[A-Z0-9][A-Z0-9-]{7,}$")
EMPTY_MARKS = {"0", "-", "－"}


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


def resolve(texts, received_on, in_stock, find_dealer):
    """合併判讀 M～P 欄，回傳要寫入車輛的值（不直接存檔，匯入與資料補正共用）。

    find_dealer(name) 回傳車行主檔物件或 None。數量 0：調出＝已調出、車行領車＝已售出（較後面的欄位較新，以最後一筆為準）；
    數量 1 卻寫調出或領車時以數量為準，只存備註。車行名稱：在庫車改實際位置，已售出記「曾放在 X」。
    """
    result = {
        "status": "", "disposition": "", "disposition_dealer": None, "disposition_dealer_name": "",
        "disposition_on": None, "current_dealer": None, "note": "",
    }
    notes = []
    for text in texts:
        raw = " ".join(str(text or "").split())
        if not raw or raw in EMPTY_MARKS:
            continue
        if IDENTIFIER.match(raw.upper()):
            notes.append(f"其他號碼：{raw}")
            continue
        parsed = parse(raw, received_on)
        kind = parsed["kind"]
        if kind in {TRANSFER_OUT, DEALER_PICKUP} and not in_stock:
            result.update(
                status="transferred_out" if kind == TRANSFER_OUT else "sold",
                disposition=kind,
                disposition_dealer=(
                    find_dealer(parsed["name"]) if parsed["name"] and parsed["name"] not in FACTORY_WORDS else None
                ),
                disposition_dealer_name=(FACTORY_LABEL if parsed["name"] in FACTORY_WORDS else parsed["name"])[:120],
                disposition_on=parsed["on"],
            )
            notes.append(parsed["note"])
            continue
        if kind == LOCATION and parsed["store"]:
            notes.append(parsed["note"])
            continue
        dealer = find_dealer(parsed["name"]) if kind == LOCATION and parsed["name"] else None
        if dealer:
            if in_stock:
                result["current_dealer"] = dealer
            else:
                notes.append(f"曾放在 {dealer.name}")
            notes.append(parsed["note"])
        else:
            notes.append(raw)
    result["note"] = "\n".join(dict.fromkeys(note for note in notes if note))
    return result
