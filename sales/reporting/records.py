"""報表明細白名單；不輸出證件、地址、電話、帳號或原始 JSON。"""
from django.core.paginator import Paginator
from django.db.models import F


RECORD_COLUMNS = {
    "number": "訂單編號", "registration_date": "領牌日期", "source": "目前銷售通路",
    "legacy_source_name": "歷史原車行", "model_number": "車型／型號", "identifier": "引擎／車身號碼",
    "energy": "DMIS 能源別", "color": "車色", "owner_name": "車主姓名", "subsidy": "補助方案",
    "payment_confirmed": "DMIS 收款確認", "total_received": "DMIS 已確認實收",
    "historical_received_price": "歷史收款價（原始）",
    "legacy_gift_card": "歷史公司禮券／匯款",
    "legacy_platform_gift": "歷史平台贈品",
    "legacy_premium": "歷史公司贈品",
    "legacy_sales_source": "原報表來源類型", "legacy_energy": "原報表能源分類",
}
DEFAULT_RECORD_COLUMNS = ["registration_date", "source", "model_number", "energy", "color", "owner_name", "payment_confirmed", "total_received"]
RECORD_NOTE = "明細依 DMIS 目前訂單與收款紀錄顯示；歷史車行、收款價、禮券與贈品保留匯入來源值，不代表目前實收、已結清或獎勵已發放。原始未填寫、欄位未提供與實際零值分開呈現；新訂單的歷史欄標為非歷史匯入。不輸出證件、聯絡資訊或原始資料中的帳號密碼。"


def record_queryset(config, filters):
    from .engine import base_query
    from .source_compatibility import sales_source_query, sales_source_expression, source_model_query, source_energy_expression
    queryset = base_query(config, filters)
    columns = config.get("records_columns", DEFAULT_RECORD_COLUMNS)
    if "legacy_sales_source" in columns:
        queryset = sales_source_query(queryset).annotate(record_source_classification=sales_source_expression())
    if "legacy_energy" in columns:
        queryset = source_model_query(queryset).annotate(record_energy_classification=source_energy_expression())
    return queryset.select_related(
        "source", "vehicle_model", "color", "allocated_vehicle", "legacy_snapshot__import_row", "operations",
    ).prefetch_related("payment_records").order_by(F(config["date_basis"]).desc(nulls_first=True), "-pk")


def record_cells(order, columns):
    legacy = getattr(order, "legacy_snapshot", None)
    operations = getattr(order, "operations", None)
    mapped = legacy.import_row.mapped_data if legacy else {}
    raw = legacy.import_row.raw_data if legacy else {}
    def original_text(key):
        if not legacy:
            return "非歷史匯入"
        if key not in raw:
            return "原始欄位未提供"
        return "原始未填寫" if raw[key] in (None, "") else str(raw[key]).strip() or "原始未填寫"
    vehicle = order.allocated_vehicle
    identifier = (vehicle.engine_number or vehicle.frame_number) if vehicle else ""
    values = {
        "number": order.number,
        "registration_date": order.registration_date.strftime("%Y/%m/%d") if order.registration_date else "日期未填寫",
        "source": order.source.name if order.source else "本店／未指定",
        "legacy_source_name": mapped.get("dealer_name_raw", "") if legacy else "非歷史匯入",
        "model_number": mapped.get("model_number") if legacy else order.vehicle_model.model_number or order.vehicle_model.name,
        "identifier": identifier or (legacy.vehicle_identifier if legacy else "") or "尚未填寫",
        "energy": order.vehicle_model.get_energy_type_display(), "color": order.color.name, "owner_name": order.owner_name,
        "subsidy": order.subsidy_type or "未填寫",
        "payment_confirmed": ("已確認" if operations.payment_confirmed else "未確認") if operations else "待補收支資料",
        "total_received": str(operations.total_received) if operations else "待補收支資料",
        "historical_received_price": str(legacy.historical_received_price) if legacy else "非歷史匯入",
        "legacy_gift_card": original_text("公司禮卷、匯款"),
        "legacy_platform_gift": original_text("平台贈品"),
        # 原 Looker Premium 對應舊 Excel「其他」，992 筆逐列核對一致（2 筆僅邊界空白）。
        "legacy_premium": original_text("其他"),
        "legacy_sales_source": getattr(order, "record_source_classification", "待核對"),
        "legacy_energy": getattr(order, "record_energy_classification", "待核對"),
    }
    if legacy and ("收款價" not in raw or raw["收款價"] in (None, "")):
        values["historical_received_price"] = original_text("收款價")
    return [{"key": key, "label": RECORD_COLUMNS[key], "value": values[key] if values[key] is not None else "未填寫"} for key in columns]


def record_context(config, filters, page_number=1):
    columns = config.get("records_columns", DEFAULT_RECORD_COLUMNS)
    page = Paginator(record_queryset(config, filters), config.get("records_page_size", 10)).get_page(page_number)
    return {"records_page": page, "records_headers": [RECORD_COLUMNS[key] for key in columns],
            "records_rows": [{"pk": order.pk, "cells": record_cells(order, columns)} for order in page], "records_note": RECORD_NOTE}
