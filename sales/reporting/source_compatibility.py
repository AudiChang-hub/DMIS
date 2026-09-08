"""原報表非財務分類的唯讀比對口徑；不覆寫 DMIS 主檔或獎金規則。"""
from django.db.models import BooleanField, Case, CharField, F, Func, Q, Value, When
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


class ImportedJsonNull(Func):
    """區分 JSON null 與字面文字 null；只接受程式內固定白名單欄位。"""
    output_field = BooleanField()

    def __init__(self, key):
        if key not in ("model_number", "dealer_name_raw"):
            raise ValueError("不支援的匯入文字欄位")
        self.key = key
        super().__init__(F("legacy_snapshot__import_row__mapped_data"))

    def as_sqlite(self, compiler, connection, **extra_context):
        sql, params = compiler.compile(self.source_expressions[0])
        return f"JSON_TYPE({sql}, %s) = 'null'", [*params, '$."' + self.key + '"']

    def as_postgresql(self, compiler, connection, **extra_context):
        sql, params = compiler.compile(self.source_expressions[0])
        return f"({sql} -> %s) = 'null'::jsonb", [*params, self.key]


def imported_text(key):
    # JSON null 與字面文字 "null" 必須區分；SQLite 與 PostgreSQL 結果保持一致。
    return Case(When(ImportedJsonNull(key), then=Value("")),
                default=KeyTextTransform(key, "legacy_snapshot__import_row__mapped_data"), output_field=CharField())


def source_model_query(queryset):
    """歷史訂單沿用匯入映射型號；新訂單以 DMIS 型號分析，不冒充原資料庫。"""
    return queryset.annotate(report_source_model=Coalesce(
        imported_text("model_number"),
        F("vehicle_model__model_number"), output_field=CharField(),
    ))


def motor_type_expression():
    return Case(*(
        When(report_source_model__in=values, then=Value(label))
        for values, label in MOTOR_TYPE_GROUPS
    ), default=Value("其他"), output_field=CharField())


SOURCE_CLASSIFICATIONS = ("馭盛", "網路平台", "店內員工", "展場", "車行")


def sales_source_query(queryset):
    """Sales Source / calc_kuiqd3i2wd：沿用歷史原車行文字，不使用正規化後的名稱。"""
    return queryset.annotate(report_source_name=Coalesce(
        imported_text("dealer_name_raw"),
        F("source__name"), Value(""), output_field=CharField(),
    ))


def sales_source_expression():
    return Case(
        When(report_source_name__in=("", "中古車", "假展場"), then=Value("馭盛")),
        When(report_source_name__in=("yahoo", "百利市", "momo", "PC", "Friday", "燦坤", "小樹購", "蝦皮", "YAHOO", "Yahoo"), then=Value("網路平台")),
        # 原式 Yahoo+假展場 中 + 是量詞而非字面加號，不能擅自改為字串包含。
        # 排除末尾換行以保持 RE2 整段匹配，避免 SQLite/Python 的 $ 尾換行特例。
        When(Q(report_source_name__regex=r"^Yahoo+假展場$") & ~Q(report_source_name__endswith="\n"), then=Value("網路平台")),
        When(report_source_name__in=("文傑", "峻生"), then=Value("店內員工")),
        When(report_source_name="展場", then=Value("展場")),
        default=Value("車行"), output_field=CharField(),
    )
