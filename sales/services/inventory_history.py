"""庫存異動紀錄的顯示：舊紀錄的異動格式不一致，統一轉成畫面用的列。

標準格式是 {欄位: {"label", "before", "after"}}；早期服務另寫過
{"status": {"before", "after"}}（無標籤、狀態為英文代碼）與 {"order": "SO…"}（單值字串），
直接顯示會出現空白列與英文代碼。這裡只轉換顯示，不改寫既有紀錄。
"""
from sales.models import VehicleInventory

# 有標籤的異動自帶 label；這裡只補早期沒有標籤的鍵（中文鍵本身就是標籤）。
FIELD_LABELS = {"status": "庫存狀態", "order": "訂單"}
STATUS_LABELS = dict(VehicleInventory.Status.choices)
STATUS_FIELDS = {"status", "庫存狀態"}


def status_change(before, after):
    """新紀錄寫入用的標準狀態異動。"""
    return {"label": "庫存狀態", "before": STATUS_LABELS.get(before, before), "after": STATUS_LABELS.get(after, after)}


def _text(value):
    if value is None:
        return ""
    return str(value)


def change_rows(changes):
    """回傳 [{label, before, after, single}]；single 為只有一個值的列（例如關聯訂單），不畫箭頭。"""
    rows = []
    for key, change in (changes or {}).items():
        if isinstance(change, dict):
            label = change.get("label") or FIELD_LABELS.get(key, key)
            if "value" in change:
                rows.append({"label": label, "before": "", "after": _text(change["value"]), "single": True})
                continue
            before, after = _text(change.get("before")), _text(change.get("after"))
            if key in STATUS_FIELDS or label == "庫存狀態":
                before, after = STATUS_LABELS.get(before, before), STATUS_LABELS.get(after, after)
            rows.append({"label": label, "before": before or "未設定", "after": after or "未設定", "single": False})
        elif _text(change).strip():
            rows.append({"label": FIELD_LABELS.get(key, key), "before": "", "after": _text(change), "single": True})
    # 單值列（關聯訂單）放最後，前後對照放前面。
    return sorted(rows, key=lambda row: row["single"])
