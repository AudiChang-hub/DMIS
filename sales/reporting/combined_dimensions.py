"""報表的組合／對應維度（T-268、T-269）。只新增維度，不改既有維度與已存報表。

- family_color「車型＋顏色」：同一車型（機種主檔，沒有主檔時用品牌＋車型名稱，同 T-228）各年式合併，
  車色依統計口徑合併（colors.report_color_expression）。鍵是字串「品牌␟車型␟車色」，沿用 v: 編碼，
  下鑽、點選連動、CSV 都走既有路徑。標籤「Saluto 125 · 盧卡綠 N34／T94」，色碼只取該車型範圍內的訂單（T-231）。
"""
from django.db.models import Case, CharField, F, Value, When
from django.db.models.functions import Coalesce, Concat

SEPARATOR = "␟"
UNFILLED_COLOR = "未填車色"


def family_color_expression():
    from .colors import report_color_expression
    brand = Coalesce(F("vehicle_model__family__brand"), F("vehicle_model__brand"), output_field=CharField())
    name = Coalesce(F("vehicle_model__family__name"), F("vehicle_model__name"), output_field=CharField())
    color = Coalesce(report_color_expression(), Value(""), output_field=CharField())
    return Case(When(vehicle_model__isnull=True, then=Value(None)),
                default=Concat(brand, Value(SEPARATOR), name, Value(SEPARATOR), color, output_field=CharField()),
                output_field=CharField())


def split_family_color(raw):
    parts = (raw or "").split(SEPARATOR)
    return (parts + ["", "", ""])[:3]


def family_color_sort_key(raw):
    """依品牌（不分大小寫，同車型篩選樹）、車型名稱、車色排列；未填排最後。"""
    if raw is None:
        return (1, "", "", "")
    brand, name, color = split_family_color(raw)
    return (0, brand.casefold(), name.casefold(), color)


def family_color_labels(queryset, keys):
    from .colors import color_code_label
    keys = [key for key in keys if key]
    if not keys:
        return {}
    codes = {}
    rows = (queryset.annotate(report_family_color_label=family_color_expression()).order_by()
            .filter(report_family_color_label__in=keys).values_list("report_family_color_label", "color__code").distinct())
    for key, code in rows:
        codes.setdefault(key, set()).add(code)
    names = {}
    for key in keys:
        brand, name, _color = split_family_color(key)
        names.setdefault(name.casefold(), set()).add(brand.casefold())
    labels = {}
    for key in keys:
        brand, name, color = split_family_color(key)
        model = f"{name}（{brand}）" if len(names[name.casefold()]) > 1 else name
        labels[key] = f"{model} · {color_code_label(color, codes.get(key, ())) if color else UNFILLED_COLOR}"
    return labels
