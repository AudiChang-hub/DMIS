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
        "records_columns": ["registration_date", "legacy_source_name", "model_number", "identifier", "energy", "color",
                            "owner_name", "subsidy", "payment_confirmed", "historical_received_price", "total_received"],
        "cards": [
            card("總車輛銷售", "stacked", "month", 24, "key_desc", series="legacy_sales_source", series_limit=20, series_other=True, series_sort="key_desc"),
            card("銷售來源占比", "donut", "legacy_sales_source", 10),
            card("銷售機種統計（原分類）", "stacked", "day", 24, "key_desc", series="legacy_motor_type", series_limit=10, series_other=False, series_sort="value"),
            card("車種分類占比", "donut", "legacy_motor_type", 10),
        ],
    }
