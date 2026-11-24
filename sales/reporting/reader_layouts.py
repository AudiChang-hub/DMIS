"""明確的閱讀版型；不以標題推測一般自訂報表的互動。"""
READER_LAYOUTS = {
    'standard': '一般報表',
    'sales_overview': '銷售總覽（原報表緊湊版型）',
    'electric_overview': '電動車銷售（三圖連動版型）',
    'gasoline_overview': '油車銷售（三圖連動版型）',
    'platform_overview': '平台銷售（月份堆疊與明細）',
    'dealer_overview': '車行銷售（車行堆疊與明細）',
    'count_overview': '車行台數（上下雙表）',
    'analysis_overview': '人口分析（直條／圓餅連動）',
}

# 台數統計頁畫面表頭用短欄名；CSV 匯出仍用原欄名，不改匯出格式。
# 車行／平台名稱由 engine.display_dimension 依固定條件命名（T-189），畫面與 CSV 一致，不在這裡縮短。
COUNT_OVERVIEW_HEADERS = {"DMIS 已分配台數獎金": "台數獎金",
                          "DMIS 車行傭金支出": "傭金"}


def display_header(config, label):
    if config.get("reader_layout") == "count_overview":
        return COUNT_OVERVIEW_HEADERS.get(label, label)
    return label


# T-311：銷售總覽類版型（#4 總車輛銷售、#5 電動車、#7 油車）把同頁的日期堆疊圖合成一張可切換細分的月份圖。
# 只看版型與圖卡種類，不改圖卡設定、查詢或數字；合併後放在第一張日期堆疊圖的位置，其餘圖卡照原順序。
MONTH_SWITCH_LAYOUTS = ("sales_overview", "electric_overview", "gasoline_overview")
# 切換鈕用短名；「比對用」等口徑說明仍寫在圖卡副標與資料口徑。
SWITCH_LABELS = {"legacy_sales_source": "銷售來源", "legacy_motor_type": "車種分類", "legacy_model": "型號"}


def _month_stack(result):
    return result["card"].get("chart") == "stacked" and result.get("date_dimension") and result["card"].get("series")


def reader_cards(config, items):
    """閱讀頁的圖卡清單：一般是 result 本身；月份切換時是 {"switch": [{"result": ..., "label": ...}, ...]}。"""
    if config.get("reader_layout") not in MONTH_SWITCH_LAYOUTS:
        return list(items)
    months = [result for result in items if _month_stack(result)]
    if len(months) < 2:
        return list(items)
    cards = []
    for result in items:
        if result is months[0]:
            cards.append({"switch": [{"result": month, "label": "依" + SWITCH_LABELS.get(
                month["card"]["series"], str(month.get("series_label") or "").split("（")[0])} for month in months]})
        elif result not in months:
            cards.append(result)
    return cards


# T-311 共用基礎：閱讀版型的明細預設只顯示常用欄，其他欄用「顯示其他 N 欄」打開（欄位、排序、CSV 都不變）。
# 台數統計明細整段預設收合、人口分組名單也收合，所以不在這裡縮欄。
RECORD_PRIMARY_COLUMNS = {
    "sales_overview": ("registration_date", "legacy_source_name", "model_number", "legacy_energy", "color", "owner_name", "payment_confirmed"),
    "electric_overview": ("registration_date", "legacy_source_name", "legacy_sales_source", "model_number", "color", "owner_name"),
    "gasoline_overview": ("registration_date", "legacy_source_name", "legacy_sales_source", "model_number", "color", "owner_name"),
    "platform_overview": ("registration_date", "legacy_dealer", "model_number", "color", "owner_name", "payment_confirmed"),
    "dealer_overview": ("registration_date", "legacy_dealer", "model_number", "color", "owner_name", "payment_confirmed"),
}


def record_extra_columns(config, columns):
    """回傳要收起來的欄位鍵；版型沒有設定常用欄，或常用欄與實際欄位對不上時不收（照舊全部顯示）。"""
    primary = RECORD_PRIMARY_COLUMNS.get(config.get("reader_layout"))
    if not primary or not any(key in primary for key in columns):
        return set()
    return {key for key in columns if key not in primary}


def reader_meta(items):
    """頁首摘要（T-311）：月份圖涵蓋的期間與張數；四款車型各一張的人口分析寫「圖表涵蓋 N 款車型」。只讀已查好的結果。"""
    if not items:
        return {}
    page_wide = [result for result in items if not result["card"].get("fixed_filters") and not result["card"].get("vehicle_model")]
    meta = {}
    if page_wide:
        meta["count"] = page_wide[0]["count"]
        months = sorted(row["label"] for result in page_wide if result.get("date_dimension") and result["card"].get("dimension") == "month"
                        for row in result["rows"] if str(row.get("label", ""))[:1].isdigit())
        if not months:
            # 車行頁（#11 #12）月份是系列不是主軸；有月份被併進「其他系列」時期間不完整，就不寫。
            for result in page_wide:
                if result["card"].get("series") != "month":
                    continue
                labels = [str(item.get("label", "")) for item in result.get("series_legend") or []]
                if "其他系列（合併）" not in labels:
                    months = sorted(label for label in labels if label[:1].isdigit())
                break
        if months:
            meta["range"] = f"{months[0]}–{months[-1]}" if months[0] != months[-1] else months[0]
    else:
        meta["count"] = sum(result["count"] for result in items)
        meta["models"] = len(items)
    return meta


def kpi_spark(items, current_month):
    """KPI「訂單」格下的每月小直條：取第一張整頁範圍的月份圖結果，進行中的月份用淡色。"""
    from decimal import Decimal, InvalidOperation
    for result in items:
        card = result["card"]
        if card.get("fixed_filters") or card.get("vehicle_model") or card.get("dimension") != "month" or result.get("retained_candidates"):
            continue
        rows = sorted((row for row in result["rows"] if str(row.get("label", ""))[:1].isdigit()), key=lambda row: row["label"])
        values = []
        for row in rows[-12:]:
            try:
                values.append((row["label"], Decimal(str(row["value"]))))
            except (InvalidOperation, TypeError):
                return []
        top = max((value for _label, value in values), default=0)
        if not values or top <= 0:
            return []
        return [{"label": label, "display": f"{value:,.0f}", "height": max(8, round(float(value / top) * 100)),
                 "partial": label == current_month} for label, value in values]
    return []
