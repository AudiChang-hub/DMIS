"""原報表重建候選設定：僅供 admin 檢查，建立後不自動發布。"""


def total_vehicle_sales():
    """p_oe0r8mk2wd 的四圖與明細；未完成跨來源逐筆對帳前保持核對版標示。"""
    def card(title, chart, dimension, limit, sort="value", **extra):
        return {"title": title, "chart": chart, "dimension": dimension, "metric": "count", "formula": "",
                "limit": limit, "sort": sort, **extra}

    return {
        "title": "總車輛銷售｜原報表核對版", "audience": "admin", "date_basis": "registration_date",
        "description": "依原報表四圖與明細建立的核對版本。資料讀取 DMIS，包含未填領牌日期；原始來源與 DMIS 筆數仍有差異，尚未完成逐筆對帳與全部互動驗收。",
        "include_undated": True, "navigation_group": "sales", "page_order": 10,
        "fixed_filters": {"model_presence": ["present"]},
        "include_records": True, "records_page_size": 10,
        "records_columns": ["registration_date", "legacy_source_name", "model_number", "identifier", "legacy_energy", "energy", "color",
                            "owner_name", "subsidy", "payment_confirmed", "historical_received_price", "total_received"],
        "cards": [
            card("總車輛銷售", "stacked", "month", 24, "key_desc", series="legacy_sales_source", series_limit=20, series_other=True, series_sort="key_desc"),
            card("銷售來源占比", "donut", "legacy_sales_source", 10),
            card("銷售機種統計（原分類）", "stacked", "day", 24, "key_desc", series="legacy_motor_type", series_limit=10, series_other=False, series_sort="value"),
            card("車種分類占比", "donut", "legacy_motor_type", 10),
        ],
    }


def electric_vehicle_sales():
    """p_v7fndtm3wd：使用原能源公式核對，不改寫 DMIS 能源與獎勵。"""
    def card(title, chart, dimension, limit, sort="value", **extra):
        return {"title": title, "chart": chart, "dimension": dimension, "metric": "count", "formula": "",
                "limit": limit, "sort": sort, **extra}

    return {
        "title": "電動車銷售統計｜原報表核對版", "audience": "admin", "date_basis": "registration_date",
        "description": "依原頁三圖與明細建立，能源採原報表公式作比對，不修改 DMIS 主檔。原 CSV 的 Pulse Ultra、EZZY 500 與可見能源公式有矛盾，另有來源未匹配資料，尚未通過跨來源驗收。歷史贈品不代表已發放，新單獎勵仍以 DMIS 為準。",
        "include_undated": True, "navigation_group": "sales", "page_order": 20,
        "fixed_filters": {"model_presence": ["present"], "legacy_energy": ["電車"]},
        "include_records": True, "records_page_size": 10,
        "records_columns": ["registration_date", "legacy_source_name", "legacy_sales_source", "model_number", "identifier", "legacy_energy", "energy", "color",
                            "owner_name", "legacy_gift_card", "legacy_platform_gift", "legacy_premium",
                            "payment_confirmed", "historical_received_price", "total_received"],
        "cards": [
            card("電動車每月銷售來源", "stacked", "month", 24, "key_desc", series="legacy_sales_source", series_limit=10, series_other=False, series_sort="value"),
            card("電動車每日銷售型號", "stacked", "day", 20, "key_desc", series="legacy_model", series_limit=20, series_other=False, series_sort="value"),
            card("電動車型號占比", "donut", "legacy_model", 20),
        ],
    }


def electric_platform_sales():
    """p_oyi9bhn3wd：月份主軸、清洗後平台名称系列，非 DMIS 通路主檔 ID。"""
    config = electric_vehicle_sales()
    config.update(title="電動車－網路平台銷售統計｜原報表核對版", page_order=40,
                  description="依原平台分頁的一張月份堆疊圖與來源明細建立。平台名稱沿用原報表清洗方式，不改寫通路主檔。原能源／來源公式與資料差異仍在核對，尚未通過跨來源完整驗收。歷史贈品記載不代表已發放。")
    config["fixed_filters"]["legacy_source"] = ["網路平台"]
    config["cards"] = [{**config["cards"][0], "title": "電動車平台每月銷售", "series": "legacy_dealer"}]
    config["records_columns"] = ["registration_date", "legacy_dealer", "model_number", "identifier", "color",
                                 "owner_name", "legacy_gift_card", "legacy_platform_gift", "legacy_premium",
                                 "payment_confirmed", "historical_received_price", "total_received"]
    return config


SOURCE_TEMPLATES = {"total": total_vehicle_sales, "electric": electric_vehicle_sales, "electric-platform": electric_platform_sales}
