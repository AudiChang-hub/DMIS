"""T-164 新增報表的起點範本；只產生草稿設定，建立後仍在設計器調整、儲存才寫入。

T-269 常用範本庫：每個範本寫明「回答什麼問題」（question），在報表設計管理的「從範本開始」顯示。
新增範本只要在 STARTERS 加一項；設定須通過 validate_config（測試逐一檢查並實際查詢一次）。
"""
import copy

from .source_templates import model_color_age_analysis


def _card(title, dimension, chart, *, metric="count", sort="key", limit=20, **extra):
    return {"title": title, "dimension": dimension, "metric": metric, "chart": chart, "formula": "", "limit": limit, "sort": sort, **extra}


def _report(title, description, cards):
    return {"title": title, "description": description, "audience": "admin", "date_basis": "registration_date",
            "navigation_group": "custom", "cards": cards}


# 依店內人員常問的問題命名；每份都是一般版型（車型×顏色×年齡層沿用大數據分析版型），可再自由增減圖表。
STARTERS = {
    "overview": {
        "label": "銷售台數分析", "summary": "品牌台數長條＋每月走勢折線，最常用的起點。",
        "question": "各品牌賣了幾台？每個月的走勢如何？",
        "kind": "bar",
        "config": lambda: _report("銷售台數分析", "依領牌日期探索銷售結構；不含草稿及取消訂單。", [
            _card("品牌銷售台數", "brand", "bar", sort="value"),
            _card("每月銷售走勢", "month", "line", limit=200),
        ]),
    },
    "trend": {
        "label": "每月銷售走勢", "summary": "看每個月賣了幾台，附逐月數字表。",
        "question": "每個月賣了幾台、車價合計多少？",
        "kind": "line",
        "config": lambda: _report("每月銷售走勢", "依領牌月份統計台數；不含草稿及取消訂單。", [
            _card("每月銷售台數", "month", "line", limit=200, width=12),
            _card("每月台數與車價合計", "month", "table", sort="key_desc", limit=24, additional_metrics=["sale_total"], width=12),
        ]),
    },
    "ranking": {
        "label": "車型排行", "summary": "哪些車型賣最多，另看各品牌占比。",
        "question": "哪些車型賣最多？各品牌占多少？",
        "kind": "donut",
        "config": lambda: _report("車型銷售排行", "依領牌日期統計各車型台數；不含草稿及取消訂單。", [
            _card("車型銷售台數排行", "model", "bar", sort="value", limit=15),
            _card("品牌占比", "brand", "donut", sort="value"),
        ]),
    },
    "channel": {
        "label": "通路與車行", "summary": "本店、車行、網路平台各占多少，車行／平台排行。",
        "question": "本店、車行、網路平台各賣了多少？哪家車行／平台最多？",
        "kind": "stacked",
        "config": lambda: _report("通路與車行銷售", "依領牌日期統計各通路與車行／平台台數；不含草稿及取消訂單。", [
            _card("來源類型占比", "source_type", "donut", sort="value"),
            _card("車行／平台台數排行", "source", "bar", sort="value", limit=20),
        ]),
    },
    # T-268：與大數據分析的預設報表「車型 顏色 vs 年齡分布」共用同一份設定（source_templates）。
    "model_color_age": {
        "label": "車型 × 顏色 × 年齡層", "summary": "每一列是車型·顏色，依年齡層分段。",
        "question": "哪些車型的哪些顏色，分別是哪些年齡層的客人買的？",
        "kind": "stacked",
        "config": model_color_age_analysis,
    },
    "dealer_energy": {
        "label": "各車行油車／電車台數", "summary": "每家車行一列，分油車、電車兩段。",
        "question": "每家車行各賣了幾台油車、幾台電車？",
        "kind": "stacked",
        "config": lambda: _report("各車行油車／電車台數", "車行單依賣出車行統計，分油車、電車（依車型主檔能源別）；不含草稿及取消訂單。", [
            _card("各車行油車／電車台數", "source", "stacked", sort="value", limit=200, series="legacy_energy", series_sort="key",
                  width=12, fixed_filters={"legacy_source": ["車行"]}),
        ]),
    },
    "finance_monthly": {
        "label": "各分期公司每月件數", "summary": "每月一根，依分期公司分段；只算分期單。",
        "question": "每個月各分期公司各做了幾件分期？",
        "kind": "stacked",
        "config": lambda: _report("各分期公司每月件數", "只算付款方式為分期的訂單；分期公司依主檔，沒有主檔時用分期公司名稱對應，對不到的列為「未填」。不含草稿及取消訂單。", [
            _card("各分期公司每月件數", "month", "stacked", limit=200, series="finance_company", series_sort="value",
                  width=12, fixed_filters={"payment_type": ["installment"]}),
        ]),
    },
    "model_sex": {
        "label": "車型 × 性別", "summary": "每個車型一列，依性別分段。",
        "question": "各車型的買家男女各占多少？",
        "kind": "stacked",
        "config": lambda: _report("車型 × 性別", "同一車型各年式合併；性別依證號辨識，公司或其他獨立列示。不含草稿及取消訂單。", [
            _card("車型 × 性別", "family", "stacked", sort="value", limit=200, series="sex", series_sort="key", width=12),
        ]),
    },
    "platform_monthly": {
        "label": "各平台每月台數", "summary": "每月一根，依網路平台分段。",
        "question": "每個月各網路平台賣了幾台？",
        "kind": "stacked",
        "config": lambda: _report("各平台每月台數", "只算網路平台單，依平台（賣出通路）分段；不含草稿及取消訂單。", [
            _card("各平台每月台數", "month", "stacked", limit=200, series="source", series_sort="value",
                  width=12, fixed_filters={"legacy_source": ["網路平台"]}),
        ]),
    },
    "blank": {
        "label": "空白報表", "summary": "只有一張圖，從頭自己設定。",
        "question": "其他問題：自己選要看的數字和分法。",
        "kind": "blank",
        "config": lambda: _report("新報表", "", [_card("新圖表", "month", "bar", limit=200)]),
    },
}
DEFAULT_STARTER = "overview"


def starter_config(key):
    """未知或未指定的起點一律回到預設範本，不接受任意設定。"""
    return copy.deepcopy(STARTERS.get(key, STARTERS[DEFAULT_STARTER])["config"]())


def starter_choices():
    return [{"key": key, "label": item["label"], "summary": item["summary"], "question": item["question"], "kind": item["kind"]}
            for key, item in STARTERS.items()]
