"""原報表重建候選設定：僅供 admin 檢查，建立後不自動發布。"""


def total_vehicle_sales():
    """p_oe0r8mk2wd 的四圖與明細；未完成跨來源逐筆對帳前保持核對版標示。"""
    def card(title, chart, dimension, limit, sort="value", **extra):
        return {"title": title, "chart": chart, "dimension": dimension, "metric": "count", "formula": "",
                "limit": limit, "sort": sort, **extra}

    return {
        "title": "總車輛銷售｜原報表核對版", "audience": "admin", "date_basis": "registration_date",
        "description": "依原報表四圖與明細建立的核對版本。資料讀取 DMIS，包含未填領牌日期；原始來源與 DMIS 筆數仍有差異，尚未完成逐筆對帳與全部互動驗收。",
        "include_undated": True, "navigation_group": "sales", "page_order": 10, "reader_layout": "sales_overview",
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
    """p_oyi9bhn3wd：月份主軸、清洗後平台名稱系列，非 DMIS 通路主檔 ID。"""
    config = electric_vehicle_sales()
    config.update(title="電動車－網路平台銷售統計｜原報表核對版", page_order=30,
                  description="依原平台分頁的一張月份堆疊圖與來源明細建立。平台名稱沿用原報表清洗方式，不改寫通路主檔。原能源／來源公式與資料差異仍在核對，尚未通過跨來源完整驗收。歷史贈品記載不代表已發放。")
    config["fixed_filters"]["legacy_source"] = ["網路平台"]
    config["cards"] = [{**config["cards"][0], "title": "電動車平台每月銷售", "series": "legacy_dealer"}]
    config["records_columns"] = ["registration_date", "legacy_dealer", "model_number", "identifier", "color",
                                 "owner_name", "legacy_gift_card", "legacy_platform_gift", "legacy_premium",
                                 "payment_confirmed", "historical_received_price", "total_received"]
    return config


def gasoline_vehicle_sales():
    """p_vi50zol3wd：保留三圖與明細，油車每日系列上限是10而非電車的20。"""
    config = electric_vehicle_sales()
    config.update(title="油車銷售統計｜原報表核對版", page_order=60,
                  description="依原油車頁三圖與明細建立；以原報表能源分類核對，不改動 DMIS 車型、訂單或財務。原分類公式與來源資料仍有待釐清差異，本頁尚未通過完整跨來源驗收。歷史禮券與贈品不代表目前已發放。")
    config["fixed_filters"]["legacy_energy"] = ["油車"]
    for card in config["cards"]:
        card["title"] = card["title"].replace("電動車", "油車")
    config["cards"][1]["series_limit"] = 10
    return config


def gasoline_platform_sales():
    """p_fatrpvn3wd：平台名稱為 Dealer_NotNull，固定油車與網路平台。"""
    config = electric_platform_sales()
    config.update(title="油車－網路平台銷售統計｜原報表核對版", page_order=70,
                  description="依原油車平台頁月份／平台堆疊與明細建立。平台名稱使用原報表清洗方式，固定油車與網路平台分類；未完成來源逐筆對帳及全部互動驗收，不改寫 DMIS 主檔、訂單或金額。")
    config["fixed_filters"]["legacy_energy"] = ["油車"]
    config["cards"][0]["title"] = "油車平台每月銷售"
    return config


def dealer_sales(gasoline=False):
    config = gasoline_platform_sales() if gasoline else electric_platform_sales()
    vehicle = "油車" if gasoline else "電動車"
    config.update(title=vehicle + "－車行銷售統計｜原報表核對版", page_order=80 if gasoline else 40)
    config["fixed_filters"]["legacy_source"] = ["車行"]
    config["description"] = "依原頁車行／月份堆疊與逐筆明細建立，原分類與 DMIS 仍待跨來源核對；電動車頁原始備註尚待安全欄位映射，尚未完整驗收。"
    config["cards"] = [{"title": vehicle + "車行每月銷售", "chart": "stacked", "dimension": "legacy_dealer",
                        "series": "month", "metric": "count", "formula": "", "limit": 50, "sort": "value",
                        "series_limit": 20, "series_other": True, "series_sort": "key_desc"}]
    config["records_columns"].remove("legacy_platform_gift")
    return config


def dealer_counts(gasoline=False):
    config = dealer_sales(gasoline)
    vehicle = "油車" if gasoline else "電動車"
    config.update(title=vehicle + "－台數統計｜原報表核對版", page_order=90 if gasoline else 50,
                  records_page_size=25,
                  description="依原頁車行台數彙總與逐筆獎勵明細建立。獎勵改讀 DMIS 已保存台數獎金分配，不套用舊報表公式；傭金與獎金分欄，不修改財務。原來源分類及表格分頁仍待完整驗收。")
    config["cards"] = [{"title": vehicle + "車行台數與獎金", "chart": "table", "dimension": "legacy_dealer",
                        "metric": "count", "formula": "", "limit": 200, "sort": "value",
                        "additional_metrics": ["dealer_bonus", "dealer_commission"]}]
    config["records_columns"] = ["registration_date", "legacy_dealer", "owner_name", "model_number", "color",
                                 "plate_number", "commission_recipient", "dealer_bonus", "dealer_commission"]
    return config


def model_analysis(kind):
    """四個車型各自固定範圍；不可用相似頁面的條件取代。"""
    is_sex = kind == "sex"
    title = "車型 X 性別" if is_sex else "車型 X 顏色"
    scopes = [
        {"model_contains": ["EV060L" if is_sex else "EV060"]},
        {"model_prefix": ["EV076"], "model_exclude": ["EV076SZV"]},
        {"model_contains" if is_sex else "model_prefix": ["EV070"]},
        {"model_exact": ["EV076SZV"]},
    ]
    return {
        "title": title + "｜原報表核對版", "audience": "admin", "date_basis": "registration_date",
        "description": "四個車型圖依原頁各自篩選。性別採已確認的新分類，保留公司或其他，不沿用舊圖排除未知性別的做法；分類差異須另行核對。資料為 DMIS，目前仍是未完成跨來源驗收的候選版本。",
        "include_undated": True, "navigation_group": "analysis", "page_order": 110 if is_sex else 120,
        "fixed_filters": {"model_presence": ["present"]}, "include_records": False,
        "cards": [
            {"title": name + ("－性別" if is_sex else "－顏色"), "chart": "donut" if is_sex else "bar",
             "dimension": kind, "metric": "count", "formula": "", "sort": "value",
             "limit": 10 if is_sex else 100, "fixed_filters": scope}
            for name, scope in zip(("FUN", "RUN", "70 皮帶", "76 皮帶"), scopes)
        ],
    }


def age_sex_analysis():
    return {
        "title": "性別 X 年齡｜原報表核對版", "audience": "admin", "date_basis": "registration_date",
        "description": "依原頁兩圖重建，年齡採當年度減出生年度。依使用者確認，生日未填、生日異常及公司或其他獨立顯示，不沿用原公式誤歸入高齡或排除未知性別的做法；其餘保留 EV 開頭、電車及 20 歲以上條件。尚待資料勾稽與完整 UI 驗收。",
        "include_undated": True, "navigation_group": "analysis", "page_order": 100,
        "fixed_filters": {"model_presence": ["present"], "legacy_energy": ["電車"],
                          "model_prefix": ["EV"], "age_scope": ["adult_or_unknown"]},
        "include_records": False,
        "cards": [
            {"title": "年齡與性別分布", "chart": "stacked", "dimension": "age_group", "series": "sex",
             "metric": "count", "formula": "", "limit": 100, "sort": "key",
             "series_limit": 10, "series_other": False, "series_sort": "value"},
            {"title": "總性別比", "chart": "donut", "dimension": "sex", "metric": "count",
             "formula": "", "limit": 10, "sort": "value"},
        ],
    }


def sex_model_color_analysis():
    config = model_analysis("sex")
    config.update(title="性別 X 車型顏色｜原報表核對版", page_order=130, include_records=True,
                  records_page_size=100, records_mode="population", records_columns=["color", "owner_name", "sex", "number"],
                  description="四個車型分別依顏色／性別呈現，保留原車型條件、使用修正性別分類。附表依車色、車主、修正性別及證號分組，每頁100組；證號暫採遮罩安全預設，僅供admin核對，跨來源差異尚未完整驗收。")
    for card in config["cards"]:
        card.update(title=card["title"] + " X 顏色", chart="stacked", dimension="color", series="sex", limit=100,
                    series_limit=10, series_other=False, series_sort="value")
    # 原頁 70 與 76 皮帶的次要排序是性別降冪，非台數降冪。
    for card in config["cards"][2:]:
        card["series_sort"] = "key_desc"
    return config


SOURCE_TEMPLATES = {"total": total_vehicle_sales, "electric": electric_vehicle_sales,
                    "electric-platform": electric_platform_sales, "gasoline": gasoline_vehicle_sales,
                    "gasoline-platform": gasoline_platform_sales,
                    "model-sex": lambda: model_analysis("sex"), "model-color": lambda: model_analysis("color"),
                    "electric-dealer": dealer_sales, "gasoline-dealer": lambda: dealer_sales(True),
                    "electric-count": dealer_counts, "gasoline-count": lambda: dealer_counts(True),
                    "age-sex": age_sex_analysis, "sex-model-color": sex_model_color_analysis}
