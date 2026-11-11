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
COUNT_OVERVIEW_HEADERS = {"原報表車行／平台名稱（比對用）": "車行", "DMIS 已分配台數獎金": "台數獎金",
                          "DMIS 車行傭金支出": "傭金"}


def display_header(config, label):
    if config.get("reader_layout") == "count_overview":
        return COUNT_OVERVIEW_HEADERS.get(label, label)
    return label
