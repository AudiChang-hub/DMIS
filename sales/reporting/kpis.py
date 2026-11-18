"""報表頁 KPI 摘要列（T-182）：只用已查好的圖卡結果組出，不另查資料庫、不改任何口徑或公式。"""
from decimal import Decimal, InvalidOperation

from .engine import FIXED_COLOR_SLOTS, NEUTRAL_LABELS, PALETTE, OTHER_COLOR

DATE_PEAK_LABELS = {"month": "單月最高", "year": "單年最高", "day": "單日最高"}
MAX_TILES = 4
MONEY_METRICS = {"dealer_bonus", "dealer_commission", "sale_total", "average_price"}


def _number(text):
    try:
        return Decimal(str(text))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _unit(result):
    metric = result["card"].get("metric")
    if metric == "count":
        return "張"
    if metric in ("sale_total", "average_price"):
        return "元"
    return ""


def _swatch(label):
    if label in NEUTRAL_LABELS:
        return OTHER_COLOR
    if label in FIXED_COLOR_SLOTS:
        return PALETTE[FIXED_COLOR_SLOTS[label]]
    return ""


def _page_wide(result):
    """只用整頁範圍一致的圖卡；各自固定車型或條件的圖（例如四款車型各一張）不放進整頁摘要。"""
    card = result["card"]
    return not card.get("fixed_filters") and not card.get("vehicle_model")


def _peak_label(result):
    # 車行／平台名稱已由 engine.display_dimension 依固定條件命名（T-189），這裡只取括號前的名稱。
    return str(result.get("dimension_label") or "分類").split("（")[0]


def reader_kpis(results):
    eligible = [result for result in results if _page_wide(result)]
    if not eligible:
        return []
    # 點選連動時，被點的那張圖保留完整候選範圍；摘要改用已套用選取的圖，數字才會跟著連動。
    applied = [result for result in eligible if not result.get("retained_candidates")] or eligible
    tiles = []
    base = applied[0]
    tiles.append({"label": "訂單", "value": f"{base['count']:,}", "unit": "張", "sub": "完整篩選範圍"})
    donut = next((result for result in applied if result["card"]["chart"] == "donut" and result["rows"]), None)
    if donut:
        ranked = sorted((row for row in donut["rows"] if row.get("percentage") is not None), key=lambda row: -row["percentage"])
        for row in ranked[:2]:
            tiles.append({"label": row["label"], "value": f"{row['percentage']:.1f}", "unit": "%",
                          "sub": f"{row['display']} {_unit(donut)}".strip(), "color": _swatch(row["label"])})
    for result in applied:
        if len(tiles) >= MAX_TILES:
            break
        card = result["card"]
        if result.get("summary_table"):
            header = (result.get("table_header_labels") or [""])[0]
            if header and len(tiles) < MAX_TILES:
                tiles.append({"label": f"{header}數", "value": f"{len(result['rows']):,}", "unit": "", "sub": "有資料的分類"})
            labels = (result.get("table_header_labels") or [])[len(result.get("table_dimension_labels") or [""]) + 1:]
            extra = card.get("additional_metrics") or []
            for position, (label, cell) in enumerate(zip(labels, (result.get("table_total_cells") or [])[1:])):
                if len(tiles) >= MAX_TILES:
                    break
                money = position < len(extra) and extra[position] in MONEY_METRICS
                tiles.append({"label": label, "value": cell["display"], "unit": "元" if money else "", "sub": "完整篩選範圍合計"})
            continue
        if card["chart"] not in ("stacked", "bar", "line") or not result["rows"]:
            continue
        rows = [row for row in result["rows"] if _number(row.get("value")) is not None]
        if card["dimension"] in DATE_PEAK_LABELS:
            dated = [row for row in rows if row["label"][:1].isdigit()]
            if dated:
                peak = max(dated, key=lambda row: _number(row["value"]))
                tiles.append({"label": DATE_PEAK_LABELS[card["dimension"]], "value": peak["display"], "unit": _unit(result), "sub": peak["label"]})
        else:
            named = [row for row in rows if row["label"] not in NEUTRAL_LABELS]
            if named:
                peak = max(named, key=lambda row: _number(row["value"]))
                share = f" · 占 {peak['percentage']:.1f}%" if peak.get("percentage") is not None else ""
                short = _peak_label(result)
                value, sub = peak["label"], f"{peak['display']} {_unit(result)}{share}".strip()
                name = peak["key"][2:] if card["dimension"] == "color" and peak["key"].startswith("v:") else ""
                if name and value.startswith(name + " "):
                    # 車色（T-231）：大字只放名稱，色碼移到小字，多個色碼時摘要卡不會被撐成好幾行。
                    value, sub = name, f"{value[len(name) + 1:]} · {sub}"
                tiles.append({"label": f"最多的{short}", "value": value, "unit": "", "sub": sub, "text": True})
    return tiles[:MAX_TILES]
