"""不再要求使用者填寫原因（使用者 2026-10-21 T-39 方案 A）。

調整／相異原因整個拿掉，由異動紀錄的前後值說明改了什麼；
重大動作（刪單、退車、改回庫存、沖銷等）的備註改為選填，空白時寫系統摘要，稽核紀錄不留空。
"""
from django.core.exceptions import ValidationError

SUMMARY_PREFIX = "系統摘要："
NOTE_LABEL = "備註（選填）"
NOTE_HELP = "可留白，系統會自動記下動作、金額與操作人。"


def optional_note(note, limit=500):
    """整理選填備註：去頭尾空白，超過上限才擋。"""
    note = (note or "").strip()
    if len(note) > limit:
        raise ValidationError(f"備註最多 {limit} 字。")
    return note


def note_or_summary(note, summary, limit=500):
    """有填備註用備註，空白時用「系統摘要：…」；結果不超過欄位長度。"""
    note = (note or "").strip()
    return (note or f"{SUMMARY_PREFIX}{summary}")[:limit]


def with_note(text, note, sep="；"):
    """在系統描述後面接上使用者的備註；沒填就只留系統描述。"""
    note = (note or "").strip()
    return f"{text}{sep}{note}" if note else text


def money(value):
    return f"${value or 0:,.0f}"


def change_text(label, before, after):
    return f"{label} {before} → {after}"


def balance_summary(action):
    """尾款和系統試算不同時寫入尾款調整原因欄；有內容代表人工尾款，重新試算時保留不動。

    不寫金額：之後的財務同步仍可能調整尾款，前後數字以異動紀錄為準。
    """
    return f"{SUMMARY_PREFIX}{action}時保留人工尾款"


def discount_summary(before, after):
    return f"{SUMMARY_PREFIX}{change_text('核定折扣', money(before), money(after))}"
