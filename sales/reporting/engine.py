"""白名單彙總查詢。禁止任意 ORM 路徑、SQL 與 Python eval。"""
import ast
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext

from django.core.exceptions import ValidationError
from django.db.models import Avg, Case, Count, F, IntegerField, Q, Sum, Value, When
from django.db.models.functions import TruncMonth, TruncYear

from sales.models import SalesOrder, SalesSource, VehicleModel, VehicleModelFamily
from .source_compatibility import SOURCE_CLASSIFICATIONS, MODEL_PRESENCE, model_presence_query, motor_type_expression, source_model_query, sales_source_expression, sales_source_query
from .source_compatibility import SOURCE_ENERGIES, source_energy_expression, source_dealer_query
from .records import RECORD_COLUMNS, DEFAULT_RECORD_COLUMNS
from .demographics import DEMOGRAPHIC_DIMENSIONS, demographic_query


DIMENSIONS = {
    "month": "月份", "brand": "品牌", "model": "車型", "energy": "能源別",
    "source": "原銷售車行／通路", "recipient": "台數與傭金歸屬車行", "county": "領牌縣市",
    "year": "年份", "day": "日期", "family": "機種", "source_type": "來源類型", "color": "車色",
    "legacy_motor_type": "舊報表車種分類（比對用）",
    "legacy_sales_source": "舊報表銷售來源（比對用）",
    "legacy_model": "原型號文字（比對用）",
    "legacy_energy": "原報表能源分類（比對用）",
    "legacy_dealer": "原報表車行／平台名稱（比對用）",
}
DIMENSIONS.update(DEMOGRAPHIC_DIMENSIONS)
METRICS = {"count": "訂單台數", "sale_total": "訂單車價合計", "average_price": "平均訂單車價", "formula": "自訂試算"}
METRICS["dealer_commission"] = "DMIS 車行傭金支出"
METRICS["dealer_bonus"] = "DMIS 已分配台數獎金"
CHARTS = {"bar": "長條圖", "line": "折線圖", "donut": "圓環占比圖", "table": "資料表", "score": "指標卡"}
CHARTS["stacked"] = "堆疊長條圖"
DATE_DIMENSIONS = ("year", "month", "day")
NAVIGATION_GROUPS = {"sales": "銷售統計", "analysis": "大數據分析", "custom": "自訂報表"}
AGGREGATES = {"count": Count("pk"), "sale_total": Sum("vehicle_price"), "average_price": Avg("vehicle_price")}
EXCLUDED_STATUSES = ["draft", "cancel_refund_pending", "cancelled"]
MAX_GROUPS = 200
PALETTE = ["#4257a5", "#278168", "#b65b33", "#9269af", "#28789d", "#a86e11", "#b3446c", "#5c6b78"]


def dimension_color(dimension, raw, index):
    categories = SOURCE_CLASSIFICATIONS if dimension == "legacy_sales_source" else ("白牌電車", "綠牌電車", "微型電車", "速克達", "擋車", "其他") if dimension == "legacy_motor_type" else ()
    return PALETTE[categories.index(raw) if raw in categories else index % len(PALETTE)]


SCOPE_LOOKUPS = {"brand": "vehicle_model__brand", "energy": "vehicle_model__energy_type",
                 "source_type": "source_type", "source": "source_id", "model": "vehicle_model_id", "legacy_source": "report_legacy_source"}
SCOPE_LABELS = {"brand": "品牌", "energy": "能源別", "source_type": "來源類型", "source": "車行／平台", "model": "指定車型", "legacy_source": "原報表銷售來源（五分類）"}
SCOPE_LOOKUPS["model_presence"] = "report_model_presence"
SCOPE_LABELS["model_presence"] = "原型號完整性（比對用）"
SCOPE_LOOKUPS["legacy_energy"] = "report_legacy_energy"
SCOPE_LABELS["legacy_energy"] = "原報表能源分類（比對用）"
MODEL_TEXT_SCOPES = {
    "model_exact": "原型號完整符合（每行一項）",
    "model_prefix": "原型號開頭符合（每行一項）",
    "model_contains": "原型號包含文字（每行一項）",
    "model_exclude": "排除完整原型號（每行一項）",
}
SCOPE_LOOKUPS.update({key: "report_source_model" for key in MODEL_TEXT_SCOPES})
SCOPE_LABELS.update(MODEL_TEXT_SCOPES)
SCOPE_LOOKUPS["age_scope"] = "report_age_scope"
SCOPE_LABELS["age_scope"] = "年齡範圍（保留未知資料）"


def validate_scope(scope):
    if not isinstance(scope, dict) or set(scope) - SCOPE_LOOKUPS.keys():
        raise ValidationError("固定條件包含不支援的欄位。")
    for key, values in scope.items():
        if not isinstance(values, list) or len(values) > 200:
            raise ValidationError("每個固定條件最多選擇 200 項。")
        for value in values:
            if not isinstance(value, str) or not value or len(value) > 100:
                raise ValidationError("固定條件格式不正確。")
            if key in ("model", "source") and (not value.isascii() or not value.isdigit() or not 0 < int(value) <= 9223372036854775807):
                raise ValidationError("固定條件的資料編號不正確。")
            choices = dict(VehicleModel.EnergyType.choices) if key == "energy" else dict(SalesOrder.SourceType.choices) if key == "source_type" else None
            if choices is not None and value not in choices:
                raise ValidationError("固定條件的分類不正確。")
            if key == "legacy_source" and value not in SOURCE_CLASSIFICATIONS:
                raise ValidationError("原報表來源分類不正確。")
            if key == "model_presence" and value not in MODEL_PRESENCE:
                raise ValidationError("原型號完整性條件不正確。")
            if key == "legacy_energy" and value not in SOURCE_ENERGIES:
                raise ValidationError("原報表能源分類不正確。")
            if key == "age_scope" and value != "adult_or_unknown":
                raise ValidationError("年齡範圍不正確。")


def scope_labels(scope):
    """顯示已保存條件；主檔已刪除時保留 ID 提醒，不默默放寬範圍。"""
    validate_scope(scope)
    items = []
    for key, values in scope.items():
        if not values:
            continue
        labels = {}
        if key == "energy":
            labels = dict(VehicleModel.EnergyType.choices)
        elif key == "source_type":
            labels = dict(SalesOrder.SourceType.choices)
        elif key == "model_presence":
            labels = MODEL_PRESENCE
        elif key == "age_scope":
            labels = {"adult_or_unknown": "20 歲以上；另列生日未填、生日異常及公司或其他"}
        elif key == "source":
            labels = {str(pk): name for pk, name in SalesSource.objects.filter(pk__in=values).values_list("pk", "name")}
        elif key == "model":
            labels = {str(model.pk): str(model) for model in VehicleModel.objects.filter(pk__in=values)}
        items.append(f"{SCOPE_LABELS[key]}：" + "、".join(labels.get(value, f"已移除項目 #{value}" if key in ("model", "source") else value) for value in values))
    return items


def formula_tree(expression):
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 200:
        raise ValidationError("公式請輸入 1–200 字。")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError, RecursionError):
        raise ValidationError("公式格式錯誤，請檢查括號與運算符號。")
    nodes = list(ast.walk(tree))
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div,
               ast.UAdd, ast.USub, ast.Name, ast.Load, ast.Constant)
    if len(nodes) > 60 or any(not isinstance(node, allowed) for node in nodes):
        raise ValidationError("公式只允許指標、數字、括號及 + − * /，不可呼叫程式或函數。")
    for node in nodes:
        if isinstance(node, ast.Name) and node.id not in AGGREGATES:
            raise ValidationError("可用指標只有 count、sale_total、average_price。")
        if isinstance(node, ast.Constant):
            if type(node.value) not in (int, float) or not Decimal(str(node.value)).is_finite() or abs(node.value) > 10**12:
                raise ValidationError("公式數字超出允許範圍。")
    return tree.body


def calculate(expression, metrics):
    tree = formula_tree(expression)

    def visit(node):
        if isinstance(node, ast.Constant):
            return Decimal(str(node.value))
        if isinstance(node, ast.Name):
            return Decimal(str(metrics[node.id] or 0))
        if isinstance(node, ast.UnaryOp):
            result = visit(node.operand)
            return -result if isinstance(node.op, ast.USub) else result
        left, right = visit(node.left), visit(node.right)
        if isinstance(node.op, ast.Add):
            result = left + right
        elif isinstance(node.op, ast.Sub):
            result = left - right
        elif isinstance(node.op, ast.Mult):
            result = left * right
        else:
            if right == 0:
                raise ZeroDivisionError
            result = left / right
        if not result.is_finite() or abs(result) > Decimal("1e30"):
            raise InvalidOperation
        return result

    try:
        with localcontext() as context:
            context.prec = 28
            return visit(tree)
    except (ZeroDivisionError, InvalidOperation):
        return None


def validate_config(config):
    required = {"title", "description", "audience", "date_basis", "cards"}
    if not isinstance(config, dict) or not required <= set(config) or set(config) - required - {"navigation_group", "page_order", "fixed_filters", "include_undated", "include_records", "records_columns", "records_page_size", "records_mode"}:
        raise ValidationError("報表設定格式不正確。")
    if type(config.get("include_undated", False)) is not bool:
        raise ValidationError("未領牌資料設定不正確。")
    if type(config.get("include_records", False)) is not bool:
        raise ValidationError("明細表設定不正確。")
    columns = config.get("records_columns", DEFAULT_RECORD_COLUMNS)
    if not isinstance(columns, list) or any(not isinstance(key, str) or key not in RECORD_COLUMNS for key in columns) or len(set(columns)) != len(columns):
        raise ValidationError("明細欄位不正確。")
    if config.get("include_records") and not columns and config.get("records_mode") != "population":
        raise ValidationError("請至少選擇一個明細欄位。")
    if type(config.get("records_page_size", 10)) is not int or config.get("records_page_size", 10) not in (10, 25, 50, 100):
        raise ValidationError("明細每頁筆數須為 10、25、50 或 100。")
    if config.get("records_mode", "orders") not in ("orders", "population"):
        raise ValidationError("明細表模式不正確。")
    if config.get("records_mode") == "population" and config["audience"] != "admin":
        raise ValidationError("人口分組附表僅供 admin 核對，不開放其他帳號。")
    validate_scope(config.get("fixed_filters", {}))
    if config.get("navigation_group", "custom") not in NAVIGATION_GROUPS:
        raise ValidationError("報表導覽分類不正確。")
    if type(config.get("page_order", 0)) is not int or not 0 <= config.get("page_order", 0) <= 999:
        raise ValidationError("頁面順序須為 0–999。")
    for key, maximum in (("title", 100), ("description", 1000)):
        if not isinstance(config[key], str) or len(config[key]) > maximum:
            raise ValidationError("報表名稱或說明過長。")
    if not config["title"].strip():
        raise ValidationError("請填寫報表名稱。")
    if config["audience"] not in ("admin", "team") or config["date_basis"] not in ("registration_date", "order_date"):
        raise ValidationError("請選擇有效的查看對象與日期依據。")
    if not isinstance(config["cards"], list) or not (0 if config.get("include_records") else 1) <= len(config["cards"]) <= 8:
        raise ValidationError("每份報表最多 8 張圖表；沒有圖表時請啟用明細表。")
    for card in config["cards"]:
        card_fields = {"title", "dimension", "metric", "chart", "formula", "limit", "sort"}
        if not isinstance(card, dict) or not card_fields <= set(card) or set(card) - card_fields - {"fixed_filters", "series", "series_limit", "series_other", "series_sort", "additional_metrics", "width", "height"}:
            raise ValidationError("圖表格式不正確。")
        if type(card.get("width", 6)) is not int or card.get("width", 6) not in (6, 12):
            raise ValidationError("圖表寬度須為半寬或全寬。")
        if "height" in card and (type(card["height"]) is not int or not 320 <= card["height"] <= 1200):
            raise ValidationError("圖表高度須為 320–1200 像素。")
        if type(card.get("series_limit", 200)) is not int or not 1 <= card.get("series_limit", 200) <= 200:
            raise ValidationError("細分系列上限須為 1–200。")
        if type(card.get("series_other", False)) is not bool:
            raise ValidationError("其他系列設定不正確。")
        if card.get("series_sort", "value") not in ("value", "key", "key_desc"):
            raise ValidationError("系列排序不正確。")
        if card.get("series", "") not in ("", *DIMENSIONS):
            raise ValidationError("細分系列不正確。")
        extra = card.get("additional_metrics", [])
        if not isinstance(extra, list) or len(extra) > 4 or any(not isinstance(key, str) or key not in METRICS or key == "formula" for key in extra) or len(set(extra)) != len(extra) or card["metric"] in extra:
            raise ValidationError("附加指標須互不重複，最多 4 項，且不能重複主要指標或使用試算公式。")
        if (extra or card["metric"] == "dealer_bonus") and card["chart"] != "table":
            raise ValidationError("附加指標及已分配台數獎金目前請使用資料表。")
        if card["chart"] == "table" and (extra or card.get("series")) and (card["metric"] == "formula" or card.get("series") == card["dimension"]):
            raise ValidationError("多欄彙總表請選不同的分類，且不使用自訂試算。")
        if card["chart"] == "stacked" and (not card.get("series") or card["series"] == card["dimension"] or card["metric"] not in ("count", "sale_total")):
            raise ValidationError("堆疊圖請選不同的分類與細分系列，指標限訂單台數或非負車價合計。")
        validate_scope(card.get("fixed_filters", {}))
        if not isinstance(card["title"], str) or not 1 <= len(card["title"].strip()) <= 100:
            raise ValidationError("每張圖表請填寫 1–100 字的標題。")
        if card["dimension"] not in DIMENSIONS or card["metric"] not in METRICS or card["chart"] not in CHARTS:
            raise ValidationError("圖表使用了不支援的欄位或圖型。")
        if type(card["limit"]) is not int or not 1 <= card["limit"] <= MAX_GROUPS or card["sort"] not in ("key", "key_desc", "value"):
            raise ValidationError("顯示筆數須為 1–200，並選擇有效排序。")
        if not isinstance(card["formula"], str) or len(card["formula"]) > 200:
            raise ValidationError("公式過長。")
        if card["metric"] == "formula":
            formula_tree(card["formula"])
        if card["chart"] == "donut" and card["metric"] not in ("count", "sale_total"):
            raise ValidationError("圓環占比請使用訂單台數或車價合計；平均與自訂試算不能相加計算占比。")
    return config


def base_query(config, filters, card=None):
    queryset = SalesOrder.objects.exclude(status__in=EXCLUDED_STATUSES)
    scopes = (config.get("fixed_filters", {}), (card or {}).get("fixed_filters", {}))
    for scope in scopes:
        validate_scope(scope)
    if any(any(scope.get(key) for key in MODEL_TEXT_SCOPES) for scope in scopes):
        queryset = source_model_query(queryset)
    if any(isinstance(scope, dict) and scope.get("model_presence") for scope in scopes):
        queryset = model_presence_query(queryset)
    if filters.get("legacy_energy") or any(isinstance(scope, dict) and scope.get("legacy_energy") for scope in scopes):
        queryset = source_model_query(queryset).annotate(report_legacy_energy=source_energy_expression())
    if filters.get("legacy_source") or any(isinstance(scope, dict) and scope.get("legacy_source") for scope in scopes):
        queryset = sales_source_query(queryset).annotate(report_legacy_source=sales_source_expression())
    # 各層皆取交集；讀者 GET 參數無法覆蓋發布版本的固定範圍。
    for scope in scopes:
        for key, values in scope.items():
            if values:
                if key in MODEL_TEXT_SCOPES:
                    if key == "model_exact":
                        queryset = queryset.filter(report_source_model__in=values)
                    elif key == "model_exclude":
                        queryset = queryset.exclude(report_source_model__in=values)
                    else:
                        condition = Q()
                        for value in values:
                            # 使用固定運算子與跳脫的文字，不接受任意 regex 或 ORM 路徑。
                            pattern = ("^" if key == "model_prefix" else "") + re.escape(value)
                            condition |= Q(report_source_model__regex=pattern)
                        queryset = queryset.filter(condition)
                    continue
                if key == "age_scope":
                    queryset = demographic_query(queryset, "age_group", "report_age_scope").exclude(report_age_scope="20歲以下")
                    continue
                queryset = queryset.filter(**{SCOPE_LOOKUPS[key] + "__in": values})
    basis = config["date_basis"]
    if basis == "registration_date" and not config.get("include_undated", False):
        queryset = queryset.filter(registration_date__isnull=False)
    for key, lookup in (("start", f"{basis}__gte"), ("end", f"{basis}__lte")):
        if filters.get(key):
            queryset = queryset.filter(**{lookup: filters[key]})
    for key, lookup in (("brand", "vehicle_model__brand"), ("energy", "vehicle_model__energy_type"),
                        ("source", "source_id"), ("source_type", "source_type"), ("legacy_source", "report_legacy_source"),
                        ("legacy_energy", "report_legacy_energy")):
        selected = filters.get(key)
        if selected:
            queryset = queryset.filter(**{lookup + "__in": selected if isinstance(selected, (list, tuple)) else [selected]})
    if filters.get("months"):
        months = Q()
        for month in filters["months"]:
            first = date.fromisoformat(month + "-01")
            interval = {basis + "__gte": first}
            if first != date(9999, 12, 1):
                interval[basis + "__lt"] = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
            months |= Q(**interval)
        queryset = queryset.filter(months)
    from .cross_filter import selections
    # 每個選取以不含 focus 的發布範圍下鑽，避免遞迴與讀者覆蓋固定條件。
    for selected in selections(filters.get("focus")):
        if selected["card"] >= len(config["cards"]):
            raise ValidationError("選取圖表已不存在，請清除選取後再試。")
        selection_filters = {key: value for key, value in filters.items() if key != "focus" and not key.startswith("_")}
        selection_filters["grain"] = selected["grain"]
        groups = selected["group"] if isinstance(selected["group"], list) else [selected["group"]]
        alternatives = Q()
        for group in groups:
            subset = drill_query(config, config["cards"][selected["card"]], selection_filters, group)
            alternatives |= Q(pk__in=subset.values("pk"))
        queryset = queryset.filter(alternatives)
    return queryset


def dimension_query(queryset, dimension, basis, alias="report_key"):
    if dimension in DEMOGRAPHIC_DIMENSIONS:
        return demographic_query(queryset, dimension, alias)
    if dimension == "legacy_dealer":
        return source_dealer_query(queryset).annotate(**{alias: F("report_dealer_label")})
    if dimension == "legacy_energy":
        return source_model_query(queryset).annotate(**{alias: source_energy_expression()})
    if dimension == "legacy_model":
        return source_model_query(queryset).annotate(**{alias: F("report_source_model")})
    if dimension == "legacy_motor_type":
        return source_model_query(queryset).annotate(**{alias: motor_type_expression()})
    if dimension == "legacy_sales_source":
        return sales_source_query(queryset).annotate(**{alias: sales_source_expression()})
    mapping = {
        "brand": "vehicle_model__brand", "model": "vehicle_model_id",
        "energy": "vehicle_model__energy_type", "source": "source_id", "county": "registration_county",
        "family": "vehicle_model__family_id", "source_type": "source_type", "color": "color__name", "day": basis,
    }
    if dimension == "month":
        expression = TruncMonth(basis)
    elif dimension == "year":
        expression = TruncYear(basis)
    elif dimension == "recipient":
        expression = Case(
            When(commission_recipient__isnull=False, then=F("commission_recipient_id")),
            When(source_type="dealer", then=F("source_id")), default=Value(None), output_field=IntegerField(),
        )
    else:
        expression = F(mapping[dimension])
    return queryset.annotate(**{alias: expression})


def effective_card(card, filters):
    """讀者的日期粒度只改變日期分類，不修改發布設定或非日期圖。"""
    grain = filters.get("_card_grain") or filters.get("grain")
    sort = filters.get("_card_sort")
    if sort:
        if sort not in ("key", "key_desc", "value"):
            raise ValidationError("圖表排序不正確。")
        card = {**card, "sort": sort}
    if grain and grain not in DATE_DIMENSIONS:
        raise ValidationError("日期粒度不正確。")
    if grain and card["dimension"] in DATE_DIMENSIONS:
        if card.get("series") == grain:
            raise ValidationError("日期粒度與細分系列相同，請改回依原設計。")
        return {**card, "dimension": grain}
    return card


def dimension_labels(dimension, keys):
    if dimension in ("source", "recipient"):
        return dict(SalesSource.objects.filter(pk__in=keys).values_list("pk", "name"))
    if dimension == "model":
        return {model.pk: f"{model.brand} / {model.name} / {model.model_year or '未填年式'} / {model.model_number}" for model in VehicleModel.objects.filter(pk__in=keys)}
    if dimension == "family":
        return {family.pk: str(family) for family in VehicleModelFamily.objects.filter(pk__in=keys)}
    if dimension == "energy":
        return dict(VehicleModel.EnergyType.choices)
    if dimension == "source_type":
        return dict(SalesOrder.SourceType.choices)
    return {}


def dimension_label(dimension, raw, labels):
    if raw is None or raw == "":
        return "日期未填寫" if dimension in DATE_DIMENSIONS else "本店／未指定通路" if dimension == "source" else "未歸屬車行" if dimension == "recipient" else "未填寫"
    if dimension in DATE_DIMENSIONS:
        return raw.strftime({"year": "%Y", "month": "%Y/%m", "day": "%Y/%m/%d"}[dimension])
    return str(labels.get(raw, raw))


def encode_key(raw):
    if raw is None:
        return "__none__"
    if isinstance(raw, str):
        return "v:" + raw
    return raw.isoformat() if isinstance(raw, date) else str(raw)


def decode_key(dimension, key):
    if not isinstance(key, str) or len(key) > 202:
        raise ValueError
    if key == "__none__":
        return None
    if dimension in ("model", "family", "source", "recipient"):
        value = int(key)
        if not 0 < value <= 9223372036854775807:
            raise ValueError
        return value
    if dimension in DATE_DIMENSIONS:
        value = date.fromisoformat(key)
        if (dimension in ("month", "year") and value.day != 1) or (dimension == "year" and value.month != 1):
            raise ValueError
        return value
    if not key.startswith("v:"):
        raise ValueError
    return key[2:]


def format_value(value):
    if value is None:
        return "無法計算（除數為零或數值超限）"
    number = Decimal(str(value))
    return f"{number:,.0f}" if number == number.to_integral() else f"{number:,.2f}"


def card_result(config, card, filters):
    card = effective_card(card, filters)
    if card["chart"] == "table" and (card.get("series") or card.get("additional_metrics") or card["metric"] == "dealer_bonus"):
        from .summary_table import summary_result
        return summary_result(config, card, filters)
    queryset = base_query(config, filters, card)
    if card["chart"] in ("donut", "stacked") and card["metric"] == "sale_total" and queryset.filter(vehicle_price__lt=0).exists():
        raise ValidationError("篩選範圍包含負車價，不適合以圓環或堆疊占比呈現，請改用資料表。")
    metric = card["metric"]
    aggregates = dict(AGGREGATES)
    if metric == "dealer_commission":
        # OneToOne 收支資料不會倍增訂單；不可再 JOIN 獎金分配後重複加總。
        aggregates.update(dealer_commission=Sum("operations__dealer_commission_expense"),
                          financial_count=Count("operations__pk"))
    totals = queryset.aggregate(**aggregates)

    def value_of(row):
        if metric == "dealer_commission" and row["financial_count"] != row["count"]:
            return None
        return calculate(card["formula"], row) if metric == "formula" else row[metric] or 0

    def display_value(value):
        if metric == "dealer_commission" and value is None:
            return "待補收支資料"
        return format_value(value)
    total = value_of(totals)
    groups = dimension_query(queryset, card["dimension"], config["date_basis"])
    # 有界查詢：最多 201 群。自訂公式先取完整的最多 200 群後排序；過量明確拒絕。
    grouped = groups.values("report_key").annotate(**aggregates).order_by("report_key")
    if card["sort"] == "key_desc":
        grouped = grouped.order_by(F("report_key").desc(nulls_last=True))
    if metric != "formula" and card["sort"] == "value":
        grouped = grouped.order_by(f"-{metric}", "report_key")
    rows = list(grouped[:MAX_GROUPS + 1])
    if len(rows) > MAX_GROUPS and metric == "formula":
        raise ValidationError("自訂試算超過 200 個群組，請縮小期間或改用其他維度。")
    truncated = len(rows) > card["limit"]
    if metric == "formula" and card["sort"] == "value":
        rows.sort(key=lambda row: (value_of(row) is not None, value_of(row) or 0), reverse=True)
    rows = rows[:card["limit"]]
    dimension = card["dimension"]
    keys = [row["report_key"] for row in rows if row["report_key"] is not None]
    labels = dimension_labels(dimension, keys)
    values = []
    for row in rows:
        raw = row["report_key"]
        value = value_of(row)
        key = encode_key(raw)
        label = dimension_label(dimension, raw, labels)
        values.append({"key": key, "label": str(label), "color": dimension_color(dimension, raw, len(values)), "value": str(value) if value is not None else None,
                       "display": display_value(value), "count": row["count"]})
    maximum = max((abs(Decimal(row["value"])) for row in values if row["value"] is not None), default=Decimal(0))
    for row in values:
        row["width"] = float(abs(Decimal(row["value"])) / maximum * 100) if maximum and row["value"] is not None else 0
        row["percentage"] = float(Decimal(row["value"]) / total * 100) if metric in ("count", "sale_total") and total and row["value"] is not None else None
    series_legend = []
    other_series_keys = []
    series_truncated = False
    if card["chart"] == "stacked":
        primary = Q(report_key__in=keys)
        if any(row["report_key"] is None for row in rows):
            primary |= Q(report_key__isnull=True)
        cells = list(dimension_query(groups.filter(primary), card["series"], config["date_basis"], "report_series")
                     .values("report_key", "report_series").annotate(**aggregates).order_by("report_key", "report_series")[:2001])
        if len(cells) > 2000:
            raise ValidationError("堆疊圖超過 2000 個細分組合，請減少顯示群數或縮小篩選範圍。")
        series_keys = list(dict.fromkeys(cell["report_series"] for cell in cells))
        series_totals = {key: 0 for key in series_keys}
        for cell in cells:
            series_totals[cell["report_series"]] += value_of(cell)
        # 依目前顯示主分類中的合計排名；同值依原始查詢順序穩定排列。
        all_series_labels = dimension_labels(card["series"], [key for key in series_keys if key is not None])
        if card.get("series_sort", "value") == "value":
            series_keys.sort(key=lambda key: series_totals[key], reverse=True)
        else:
            series_keys.sort(key=lambda key: dimension_label(card["series"], key, all_series_labels), reverse=card["series_sort"] == "key_desc")
        other_series_keys = series_keys[card.get("series_limit", 200):]
        series_truncated = bool(other_series_keys)
        series_keys = series_keys[:card.get("series_limit", 200)]
        series_labels = all_series_labels
        colors = {key: dimension_color(card["series"], key, index) for index, key in enumerate(series_keys)}
        series_legend = [{"label": dimension_label(card["series"], key, series_labels), "color": colors[key]} for key in series_keys]
        if other_series_keys and card.get("series_other"):
            series_legend.append({"label": "其他系列（合併）", "color": "#66717d"})
        primary_values = {row["key"]: row for row in values}
        series_rank = {key: index for index, key in enumerate(series_keys)}
        for row in values:
            row["segments"] = []
        for cell in sorted(cells, key=lambda cell: series_rank.get(cell["report_series"], len(series_keys))):
            if cell["report_series"] in other_series_keys:
                continue
            parent = primary_values[encode_key(cell["report_key"])]
            value = value_of(cell)
            label = dimension_label(card["series"], cell["report_series"], series_labels)
            parent["segments"].append({"key": "c:" + json.dumps([parent["key"], encode_key(cell["report_series"])], separators=(",", ":")),
                "label": label, "point_label": parent["label"] + " · " + label, "value": str(value), "display": display_value(value),
                "count": cell["count"], "color": colors[cell["report_series"]],
                "width": float(value / Decimal(parent["value"]) * 100) if Decimal(parent["value"]) else 0})
        if other_series_keys and card.get("series_other"):
            for parent in values:
                omitted = [cell for cell in cells if encode_key(cell["report_key"]) == parent["key"] and cell["report_series"] in other_series_keys]
                if not omitted:
                    continue
                value = sum(value_of(cell) for cell in omitted)
                parent["segments"].append({"key": "o:" + parent["key"], "label": "其他系列（合併）",
                    "point_label": parent["label"] + " · 其他系列（合併）", "value": str(value), "display": display_value(value),
                    "count": sum(cell["count"] for cell in omitted), "color": "#66717d",
                    "width": float(value / Decimal(parent["value"]) * 100) if Decimal(parent["value"]) else 0})
    if card["chart"] == "donut" and (metric not in ("count", "sale_total") or any(Decimal(row["value"] or 0) < 0 for row in values)):
        raise ValidationError("圓環占比不支援平均、試算或負值，請改用資料表。")
    financial_note = ""
    if metric == "dealer_commission":
        financial_note = "讀取 DMIS 保存的車行傭金支出（可能含已分配獎金），不代表已付款；報表不重算或重複加計獎金。"
        missing = totals["count"] - totals["financial_count"]
        if missing:
            financial_note += f" 其中 {missing} 張訂單缺少收支資料，合計暫不顯示，請由來源訂單補齊。"
    return {"card": card, "rows": values, "total": display_value(total), "count": totals["count"],
            "compatibility_note": ("比對用分類：依已核對的原型號、車種／能源／來源公式；歷史訂單使用匯入型號／原車行文字，新訂單使用 DMIS 主檔。各公式的整段匹配、字首、大小寫與加號規則不同。不影響車型、傭金或獎金規則，亦不代表兩套來源資料已逐筆核對。"
                                   if {"legacy_motor_type", "legacy_sales_source", "legacy_model", "legacy_energy", "legacy_dealer"}.intersection((dimension, card.get("series"))) else ""),
            "scope_labels": scope_labels(card.get("fixed_filters", {})),
            "financial_note": financial_note,
            "series_legend": series_legend, "series_label": DIMENSIONS.get(card.get("series"), ""),
            "series_truncated": series_truncated, "other_series_keys": other_series_keys,
            "raw_total": str(total) if total is not None else None,
            "truncated": truncated, "metric_label": METRICS[metric], "dimension_label": DIMENSIONS[dimension]}


def drill_query(config, card, filters, key):
    card = effective_card(card, filters)
    queryset = dimension_query(base_query(config, filters, card), card["dimension"], config["date_basis"])
    if key == "__all__":
        return queryset
    try:
        if isinstance(key, str) and key.startswith("o:"):
            if card["chart"] != "stacked" or not card.get("series_other"):
                raise ValueError
            parent = decode_key(card["dimension"], key[2:])
            omitted = card_result(config, card, filters)["other_series_keys"]
            conditions = Q(report_series__in=[value for value in omitted if value is not None])
            if None in omitted:
                conditions |= Q(report_series__isnull=True)
            return dimension_query(queryset, card["series"], config["date_basis"], "report_series").filter(conditions, report_key=parent)
        if isinstance(key, str) and key.startswith("c:"):
            if card["chart"] not in ("stacked", "table") or not card.get("series") or len(key) > 600:
                raise ValueError
            pair = json.loads(key[2:])
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError
            queryset = dimension_query(queryset, card["series"], config["date_basis"], "report_series")
            return queryset.filter(report_key=decode_key(card["dimension"], pair[0]), report_series=decode_key(card["series"], pair[1]))
        key = decode_key(card["dimension"], key)
    except (ValueError, TypeError, RecursionError):
        raise ValidationError("明細條件不正確。")
    return queryset.filter(report_key=key)
