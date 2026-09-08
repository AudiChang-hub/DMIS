"""報表明細白名單；不輸出證件、地址、電話、帳號或原始 JSON。"""
from django.core.paginator import Paginator
from django.db.models import F


RECORD_COLUMNS = {
    "number": "訂單編號", "registration_date": "領牌日期", "source": "目前銷售通路",
    "legacy_source_name": "歷史原車行", "model_number": "車型／型號", "identifier": "引擎／車身號碼",
    "energy": "能源別", "color": "車色", "owner_name": "車主姓名", "subsidy": "補助方案",
    "payment_confirmed": "DMIS 收款確認", "total_received": "DMIS 已確認實收",
    "historical_received_price": "歷史收款價（原始）",
}
DEFAULT_RECORD_COLUMNS = ["registration_date", "source", "model_number", "energy", "color", "owner_name", "payment_confirmed", "total_received"]
RECORD_NOTE = "明細依 DMIS 目前訂單與收款紀錄顯示；歷史原車行與歷史收款價保留匯入來源原值，不代表目前實收或已結清。不輸出證件、聯絡資訊或原始資料中的帳號密碼。"


def record_queryset(config, filters):
    from .engine import base_query
    return base_query(config, filters).select_related(
        "source", "vehicle_model", "color", "allocated_vehicle", "legacy_snapshot__import_row", "operations",
    ).prefetch_related("payment_records").order_by(F(config["date_basis"]).desc(nulls_first=True), "-pk")


def record_cells(order, columns):
    legacy = getattr(order, "legacy_snapshot", None)
    operations = getattr(order, "operations", None)
    mapped = legacy.import_row.mapped_data if legacy else {}
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
    }
    return [{"key": key, "label": RECORD_COLUMNS[key], "value": values[key] if values[key] is not None else "未填寫"} for key in columns]


def record_context(config, filters, page_number=1):
    columns = config.get("records_columns", DEFAULT_RECORD_COLUMNS)
    page = Paginator(record_queryset(config, filters), config.get("records_page_size", 10)).get_page(page_number)
    return {"records_page": page, "records_headers": [RECORD_COLUMNS[key] for key in columns],
            "records_rows": [{"pk": order.pk, "cells": record_cells(order, columns)} for order in page], "records_note": RECORD_NOTE}
