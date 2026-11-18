"""報表的車色統計口徑（T-228）。

同一個廣告色在不同年式色碼不同時，車色主檔會用「名稱（年式代號）」分開，例如
「盧卡綠（UC125D）」T94、「盧卡綠（UC125D2）」N34（T-223）。報表依車色統計時
把結尾括號內的年式／型號代號（只含英數字、點、連字號）去掉，算成同一個「盧卡綠」。
括號內是中文等其他說明的（例如「黑（消光）」）視為不同顏色，不合併。

只影響報表中心的車色分組與人口附表；訂單、車色主檔與明細的「名稱 色碼」顯示都不變。

顯示（T-231）：分組仍以統計用名稱為準，標籤寫成「名稱 色碼」；合併後有多個色碼時全部列出，
例如「盧卡綠 N34／T94」（與 T-229 庫存車色篩選「白 RB5／W13」同一寫法），沒有色碼只顯示名稱。
色碼取自該圖範圍內的訂單車色，所以單一車種的圖只列該車種的色碼。
"""
import re

from django.db.models import Case, CharField, F, Q, Value, When

from sales.models import VehicleColor

CODE_SUFFIX = re.compile(r"\s*[（(]\s*[A-Za-z0-9][A-Za-z0-9.\-]*\s*[）)]\s*$")


def report_color_name(name):
    """統計用車色名稱；去掉後變空白時保留原名。"""
    name = (name or "").strip()
    return CODE_SUFFIX.sub("", name) or name


def color_code_label(name, codes):
    """「名稱 色碼」；多個色碼依字母排序以「／」連接，空白色碼略過。"""
    codes = sorted({(code or "").strip() for code in codes} - {""})
    return f"{name} {'／'.join(codes)}" if codes else name


def report_color_labels(queryset, names=None):
    """{統計用車色名稱: 顯示標籤}；色碼取自 queryset 內訂單的車色。names 給定時只查這些名稱。"""
    rows = queryset.annotate(report_color_label_key=report_color_expression()).order_by()
    if names is not None:
        rows = rows.filter(report_color_label_key__in=[name for name in names if name])
    codes = {}
    for name, code in rows.values_list("report_color_label_key", "color__code").distinct():
        if name:
            codes.setdefault(name, set()).add(code)
    return {name: color_code_label(name, values) for name, values in codes.items()}


def report_color_expression(field="color__name"):
    """統計用車色名稱的查詢運算式：只把需要合併的名稱改寫，其餘照原欄位。"""
    names = (VehicleColor.objects.filter(Q(name__contains="（") | Q(name__contains="("))
             .values_list("name", flat=True).distinct())
    merged = {}
    for name in names:
        target = report_color_name(name)
        if target != name:
            merged.setdefault(target, []).append(name)
    if not merged:
        return F(field)
    return Case(*[When(**{f"{field}__in": sorted(sources)}, then=Value(target)) for target, sources in sorted(merged.items())],
                default=F(field), output_field=CharField())
