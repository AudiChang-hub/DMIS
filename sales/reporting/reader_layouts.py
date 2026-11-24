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
