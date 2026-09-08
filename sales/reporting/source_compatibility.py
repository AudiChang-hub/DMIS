"""原報表非財務分類的唯讀比對口徑；不覆寫 DMIS 主檔或獎金規則。"""
from django.db.models import Case, CharField, F, Value, When
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Coalesce


# 2026-09-08 原報表 MotorType / calc_l2y60pz9wd 實際公式。
# REGEXP_MATCH 是整段匹配，不能替換為 contains 或 regex 搜尋。
# 原公式只有有限文字選項，展開為精確 IN 比對，避免資料庫 regex 方言差異。
MOTOR_TYPE_GROUPS = (
    (("EV062", "EV060L", "EV076", "EV070V", "EV076S", "EV076SZV", "Gogoro", "Pulse", "S2 ABS", "S2ABS"), "白牌電車"),
    (("JEGO", "VIVA", "EZ1", "EZZY", "Ur2"), "綠牌電車"),
    (("BOBE", "SHINE", "TSV57", "M02", "M01", "JDL-B1"), "微型電車"),
    (("UQ", "UC", "UG", "UT", "UT125XZ"), "速克達"),
    (("DRZ-4SM", "GSX", "DS", "DS250"), "擋車"),
)


def source_model_query(queryset):
    """歷史訂單沿用匯入映射型號；新訂單以 DMIS 型號分析，不冒充原資料庫。"""
    return queryset.annotate(report_source_model=Coalesce(
        KeyTextTransform("model_number", "legacy_snapshot__import_row__mapped_data"),
        F("vehicle_model__model_number"), output_field=CharField(),
    ))


def motor_type_expression():
    return Case(*(
        When(report_source_model__in=values, then=Value(label))
        for values, label in MOTOR_TYPE_GROUPS
    ), default=Value("其他"), output_field=CharField())
