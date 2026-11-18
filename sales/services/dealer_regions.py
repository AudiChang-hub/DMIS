"""車行多選依區域分組（T-234，使用者 2026-11-18）。

分組與排序沿用車行聯絡資料頁：`SalesSource.city`（縣市），依 `TaiwanCounty` 順序；沒填縣市歸最後的「未分區」。
只影響選單怎麼排、怎麼分組，選項的值與篩選結果不變。
"""
from sales.models import SalesSource, TaiwanCounty

UNASSIGNED = "未分區"
UNASSIGNED_ORDER = len(TaiwanCounty.choices)
_ORDER = {value: index for index, (value, _) in enumerate(TaiwanCounty.choices)}


def region_order(city):
    return _ORDER.get(city or "", UNASSIGNED_ORDER)


def region_label(city):
    return city if city in _ORDER else UNASSIGNED


def option_attrs(city):
    """可搜尋多選（searchable-select）選項用的 data 屬性。"""
    return {"data-region": region_label(city), "data-region-order": str(region_order(city))}


def group_choices(choices, city_of):
    """[(值, 名稱)] 依區域分組：[{"label", "count", "choices"}]，區內維持原順序。"""
    groups = {}
    for value, text in choices:
        city = city_of(value)
        key = city if city in _ORDER else UNASSIGNED
        groups.setdefault(key, []).append((value, text))
    ordered = sorted(groups.items(), key=lambda item: region_order(item[0] if item[0] != UNASSIGNED else ""))
    return [{"label": label, "count": len(items), "choices": items} for label, items in ordered]


def dealer_city_by_pk():
    return dict(SalesSource.objects.filter(source_type=SalesSource.SourceType.DEALER).values_list("pk", "city"))


def report_label_key(text):
    """報表「車行／平台」標籤的比對鍵：與 source_dealer_query 相同，去掉 ASCII 空白後轉大寫。"""
    cleaned = str(text or "")
    for whitespace in (" ", "\t", "\n", "\f", "\r"):
        cleaned = cleaned.replace(whitespace, "")
    return cleaned.strip().upper()


def dealer_city_by_report_label():
    cities = {}
    for name, city in SalesSource.objects.filter(source_type=SalesSource.SourceType.DEALER).order_by("pk").values_list("name", "city"):
        cities.setdefault(report_label_key(name), city)
    return cities
