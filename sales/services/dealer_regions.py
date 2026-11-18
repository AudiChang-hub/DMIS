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


PLATFORM_GROUP = "網路平台"
HOME_GROUP = "本店"


def group_mixed_choices(choices, kind_of, city_of):
    """車行／平台混合清單分組（T-235，使用者 2026-11-18「要分」）：網路平台一組、本店（馭盛、永湛）一組放最上面，
    車行依縣市分區，其餘（對不到主檔、其他本店來源）歸最後的「未分區」。kind_of(值) 回傳 dealer／platform／store。"""
    from sales.services.home_stores import home_store_labels

    home = home_store_labels()
    platforms, homes, rest = [], [], []
    for value, text in choices:
        kind = kind_of(value)
        if kind == SalesSource.SourceType.PLATFORM:
            platforms.append((value, text))
        elif kind == SalesSource.SourceType.STORE and text in home:
            homes.append((value, text))
        else:
            rest.append((value, text))
    homes.sort(key=lambda item: home.index(item[1]))
    groups = [{"label": label, "count": len(items), "choices": items}
              for label, items in ((PLATFORM_GROUP, platforms), (HOME_GROUP, homes)) if items]
    rest_kinds = {value: kind_of(value) for value, _ in rest}
    return groups + group_choices(rest, lambda value: city_of(value) if rest_kinds[value] == SalesSource.SourceType.DEALER else "")
