"""T-164 新增報表的起點範本；只產生草稿設定，建立後仍在設計器調整、儲存才寫入。"""
import copy


def _card(title, dimension, chart, *, metric="count", sort="key", limit=20, **extra):
    return {"title": title, "dimension": dimension, "metric": metric, "chart": chart, "formula": "", "limit": limit, "sort": sort, **extra}


def _report(title, description, cards):
    return {"title": title, "description": description, "audience": "admin", "date_basis": "registration_date",
            "navigation_group": "custom", "cards": cards}


# 依店內人員常問的問題命名；每份都是一般版型，可再自由增減圖表。
STARTERS = {
    "overview": {
        "label": "銷售台數分析", "summary": "品牌台數長條＋每月走勢折線，最常用的起點。",
        "kind": "bar",
        "config": lambda: _report("銷售台數分析", "依領牌日期探索銷售結構；不含草稿及取消訂單。", [
            _card("品牌銷售台數", "brand", "bar", sort="value"),
            _card("每月銷售走勢", "month", "line", limit=200),
        ]),
    },
    "trend": {
        "label": "每月銷售走勢", "summary": "看每個月賣了幾台，附逐月數字表。",
        "kind": "line",
        "config": lambda: _report("每月銷售走勢", "依領牌月份統計台數；不含草稿及取消訂單。", [
            _card("每月銷售台數", "month", "line", limit=200, width=12),
            _card("每月台數與車價合計", "month", "table", sort="key_desc", limit=24, additional_metrics=["sale_total"], width=12),
        ]),
    },
    "ranking": {
        "label": "車型排行", "summary": "哪些車型賣最多，另看各品牌占比。",
        "kind": "donut",
        "config": lambda: _report("車型銷售排行", "依領牌日期統計各車型台數；不含草稿及取消訂單。", [
            _card("車型銷售台數排行", "model", "bar", sort="value", limit=15),
            _card("品牌占比", "brand", "donut", sort="value"),
        ]),
    },
    "channel": {
        "label": "通路與車行", "summary": "本店、車行、網路平台各占多少，車行／平台排行。",
        "kind": "stacked",
        "config": lambda: _report("通路與車行銷售", "依領牌日期統計各通路與車行／平台台數；不含草稿及取消訂單。", [
            _card("來源類型占比", "source_type", "donut", sort="value"),
            _card("車行／平台台數排行", "source", "bar", sort="value", limit=20),
        ]),
    },
    "blank": {
        "label": "空白報表", "summary": "只有一張圖，從頭自己設定。",
        "kind": "blank",
        "config": lambda: _report("新報表", "", [_card("新圖表", "month", "bar", limit=200)]),
    },
}
DEFAULT_STARTER = "overview"


def starter_config(key):
    """未知或未指定的起點一律回到預設範本，不接受任意設定。"""
    return copy.deepcopy(STARTERS.get(key, STARTERS[DEFAULT_STARTER])["config"]())


def starter_choices():
    return [{"key": key, "label": item["label"], "summary": item["summary"], "kind": item["kind"]} for key, item in STARTERS.items()]
