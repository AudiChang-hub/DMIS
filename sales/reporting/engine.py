"""白名單彙總查詢。禁止任意 ORM 路徑、SQL 與 Python eval。"""
import ast
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext

from django.core.exceptions import ValidationError
from django.db.models import Avg, Case, Count, F, IntegerField, Sum, Value, When
from django.db.models.functions import TruncMonth

from sales.models import SalesOrder, SalesSource, VehicleModel


DIMENSIONS = {
    "month": "月份", "brand": "品牌", "model": "車型", "energy": "能源別",
    "source": "原銷售車行／通路", "recipient": "台數與傭金歸屬車行", "county": "領牌縣市",
}
METRICS = {"count": "訂單台數", "sale_total": "訂單車價合計", "average_price": "平均訂單車價", "formula": "自訂試算"}
CHARTS = {"bar": "長條圖", "line": "折線圖", "table": "資料表", "score": "指標卡"}
AGGREGATES = {"count": Count("pk"), "sale_total": Sum("vehicle_price"), "average_price": Avg("vehicle_price")}
EXCLUDED_STATUSES = ["draft", "cancel_refund_pending", "cancelled"]
MAX_GROUPS = 200


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
    if not isinstance(config, dict) or set(config) != {"title", "description", "audience", "date_basis", "cards"}:
        raise ValidationError("報表設定格式不正確。")
    for key, maximum in (("title", 100), ("description", 1000)):
        if not isinstance(config[key], str) or len(config[key]) > maximum:
            raise ValidationError("報表名稱或說明過長。")
    if not config["title"].strip():
        raise ValidationError("請填寫報表名稱。")
    if config["audience"] not in ("admin", "team") or config["date_basis"] not in ("registration_date", "order_date"):
        raise ValidationError("請選擇有效的查看對象與日期依據。")
    if not isinstance(config["cards"], list) or not 1 <= len(config["cards"]) <= 8:
        raise ValidationError("每份報表請保留 1–8 張圖表。")
    for card in config["cards"]:
        if not isinstance(card, dict) or set(card) != {"title", "dimension", "metric", "chart", "formula", "limit", "sort"}:
            raise ValidationError("圖表格式不正確。")
        if not isinstance(card["title"], str) or not 1 <= len(card["title"].strip()) <= 100:
            raise ValidationError("每張圖表請填寫 1–100 字的標題。")
        if card["dimension"] not in DIMENSIONS or card["metric"] not in METRICS or card["chart"] not in CHARTS:
            raise ValidationError("圖表使用了不支援的欄位或圖型。")
        if type(card["limit"]) is not int or not 1 <= card["limit"] <= MAX_GROUPS or card["sort"] not in ("key", "value"):
            raise ValidationError("顯示筆數須為 1–200，並選擇有效排序。")
        if not isinstance(card["formula"], str) or len(card["formula"]) > 200:
            raise ValidationError("公式過長。")
        if card["metric"] == "formula":
            formula_tree(card["formula"])
    return config


def base_query(config, filters):
    queryset = SalesOrder.objects.exclude(status__in=EXCLUDED_STATUSES)
    basis = config["date_basis"]
    if basis == "registration_date":
        queryset = queryset.filter(registration_date__isnull=False)
    for key, lookup in (("start", f"{basis}__gte"), ("end", f"{basis}__lte")):
        if filters.get(key):
            queryset = queryset.filter(**{lookup: filters[key]})
    if filters.get("brand"):
        queryset = queryset.filter(vehicle_model__brand=filters["brand"])
    if filters.get("energy"):
        queryset = queryset.filter(vehicle_model__energy_type=filters["energy"])
    return queryset


def dimension_query(queryset, dimension, basis):
    mapping = {
        "brand": "vehicle_model__brand", "model": "vehicle_model_id",
        "energy": "vehicle_model__energy_type", "source": "source_id", "county": "registration_county",
    }
    if dimension == "month":
        expression = TruncMonth(basis)
    elif dimension == "recipient":
        expression = Case(
            When(commission_recipient__isnull=False, then=F("commission_recipient_id")),
            When(source_type="dealer", then=F("source_id")), default=Value(None), output_field=IntegerField(),
        )
    else:
        expression = F(mapping[dimension])
    return queryset.annotate(report_key=expression)


def format_value(value):
    if value is None:
        return "無法計算（除數為零或數值超限）"
    number = Decimal(str(value))
    return f"{number:,.0f}" if number == number.to_integral() else f"{number:,.2f}"


def card_result(config, card, filters):
    queryset = base_query(config, filters)
    totals = queryset.aggregate(**AGGREGATES)
    metric = card["metric"]
    value_of = lambda row: calculate(card["formula"], row) if metric == "formula" else row[metric] or 0
    total = value_of(totals)
    groups = dimension_query(queryset, card["dimension"], config["date_basis"])
    # 有界查詢：最多 201 群。自訂公式先取完整的最多 200 群後排序；過量明確拒絕。
    grouped = groups.values("report_key").annotate(**AGGREGATES).order_by("report_key")
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
    labels = {}
    if dimension in ("source", "recipient"):
        labels = dict(SalesSource.objects.filter(pk__in=keys).values_list("pk", "name"))
    elif dimension == "model":
        labels = {model.pk: f"{model.brand} / {model.name} / {model.model_year or '未填年式'} / {model.model_number}" for model in VehicleModel.objects.filter(pk__in=keys)}
    elif dimension == "energy":
        labels = dict(VehicleModel.EnergyType.choices)
    values = []
    for row in rows:
        raw = row["report_key"]
        value = value_of(row)
        key = raw.isoformat() if isinstance(raw, date) else str(raw) if raw is not None else "__none__"
        if isinstance(raw, str):
            key = "v:" + raw
        label = labels.get(raw, raw)
        if dimension == "month" and raw:
            label = raw.strftime("%Y/%m")
        if raw is None or raw == "":
            label = "本店／未指定通路" if dimension == "source" else "未歸屬車行" if dimension == "recipient" else "未填寫"
        values.append({"key": key, "label": str(label), "value": str(value) if value is not None else None,
                       "display": format_value(value), "count": row["count"]})
    maximum = max((abs(Decimal(row["value"])) for row in values if row["value"] is not None), default=Decimal(0))
    for row in values:
        row["width"] = float(abs(Decimal(row["value"])) / maximum * 100) if maximum and row["value"] is not None else 0
    return {"card": card, "rows": values, "total": format_value(total), "count": totals["count"],
            "truncated": truncated, "metric_label": METRICS[metric], "dimension_label": DIMENSIONS[dimension]}


def drill_query(config, card, filters, key):
    queryset = dimension_query(base_query(config, filters), card["dimension"], config["date_basis"])
    if key == "__all__":
        return queryset
    if key == "__none__":
        return queryset.filter(report_key__isnull=True)
    try:
        if card["dimension"] in ("model", "source", "recipient"):
            key = int(key)
            if not 0 < key <= 9223372036854775807:
                raise ValueError
        elif card["dimension"] == "month":
            key = date.fromisoformat(key)
            if key.day != 1:
                raise ValueError
        else:
            if not key.startswith("v:") or len(key) > 102:
                raise ValueError
            key = key[2:]
    except (ValueError, TypeError):
        raise ValidationError("明細條件不正確。")
    return queryset.filter(report_key=key)
