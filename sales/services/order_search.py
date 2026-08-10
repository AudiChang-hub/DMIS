from pathlib import PurePath

import django_rq
from django.conf import settings
from django.db import transaction
from django.db import models
from django.db.models import Q

from sales.models import (
    AccessoryLine,
    OrderOperationsProfile,
    PaymentRecord,
    RegistrationDocument,
    SalesOrder,
    SalesOrderSearchIndex,
    SubsidyDocument,
    VehicleInventory,
    VehicleModel,
)


INTERNAL_FIELDS = {
    "id",
    "revision",
    "editing_session",
    "editing_at",
}
SENSITIVE_FIELDS = {
    "owner_id_number",
    "old_owner_id_number",
    "old_owner_ocr_id_number",
}
SEARCHABLE_TYPES = (
    models.CharField,
    models.TextField,
    models.EmailField,
    models.DateField,
    models.DateTimeField,
    models.DecimalField,
    models.IntegerField,
    models.BooleanField,
    models.FileField,
)

RELATED_FIELDS = (
    ("source__name", "來源名稱"),
    ("vehicle_model__brand", "廠牌"),
    ("vehicle_model__name", "車型"),
    ("vehicle_model__model_number", "型號"),
    ("vehicle_model__model_year", "年份"),
    ("vehicle_model__model_code", "型式"),
    ("vehicle_model__energy_type", "動力類型"),
    ("vehicle_model__displacement_cc", "排氣量"),
    ("vehicle_model__suggested_price", "建議售價"),
    ("color__name", "車色"),
    ("allocated_vehicle__engine_number", "引擎號碼"),
    ("allocated_vehicle__frame_number", "車身號碼"),
    ("allocated_vehicle__location_store__name", "目前位置"),
    ("allocated_vehicle__condition_note", "車況說明"),
    ("allocated_vehicle__condition_resolution", "車況處理結果"),
    ("allocated_vehicle__received_on", "進車日期"),
    ("allocated_vehicle__status", "庫存狀態"),
    ("accessories__name", "配件名稱"),
    ("accessories__quantity", "配件數量"),
    ("accessories__line_type", "配件類型"),
    ("accessories__amount", "配件售價"),
    ("accessories__labor_fee", "配件工資"),
    ("accessories__note", "配件備註"),
    ("other_fees__name", "其他費用項目"),
    ("other_fees__amount", "其他費用金額"),
    ("subsidy_documents__document_type", "補助文件類型"),
    ("subsidy_documents__name", "補助文件名稱"),
    ("subsidy_documents__note", "補助文件備註"),
    ("subsidy_documents__file", "補助文件檔名"),
    ("subsidy_documents__uploaded_by", "補助文件上傳人員"),
    ("registration_documents__document_type", "領牌文件類型"),
    ("registration_documents__name", "領牌文件名稱"),
    ("registration_documents__file", "領牌文件檔名"),
    ("registration_documents__uploaded_by", "領牌文件上傳人員"),
    ("events__event_type", "處理紀錄類型"),
    ("events__description", "處理紀錄內容"),
    ("events__actor_name", "處理人員"),
    ("changes__reason", "訂單變更原因"),
    ("changes__actor_name", "訂單修改人員"),
    ("operations__dealer_name", "車行"),
    ("operations__balance_invoice_number", "尾款發票號碼"),
    ("operations__bank_name", "銀行"),
    ("operations__old_vehicle_engine_number", "舊車引擎號碼"),
    ("operations__old_vehicle_brand", "舊車廠牌"),
    ("operations__vehicle_control_account", "車控帳號"),
    ("operations__battery_plan", "電池合約方案"),
    ("operations__battery_account", "電池合約帳號"),
    ("operations__helmet", "安全帽"),
    ("operations__company_gift_or_remittance", "公司禮券、匯款"),
    ("operations__platform_gift", "平台贈品"),
    ("operations__other_fulfillment", "其他履約內容"),
    ("operations__customer_service_phone", "客服電話"),
    ("operations__installment_info", "分期資訊"),
    ("payment_records__item_name", "收款項目"),
    ("payment_records__payment_method", "收款方式"),
    ("payment_records__receiving_account", "收款帳戶"),
    ("payment_records__note", "收款備註"),
    ("subsidy_items__category", "補助類別"),
    ("subsidy_items__item_name", "補助項目"),
    ("subsidy_items__expected_amount", "補助預計金額"),
    ("subsidy_items__status", "補助狀態"),
)


def _normalise(value):
    return (
        str(value or "")
        .strip()
        .casefold()
        .replace(" ", "")
        .replace("-", "")
        .replace("/", "")
        .replace("／", "")
    )


def _contains(value, query):
    raw_value = str(value or "").casefold()
    raw_query = str(query or "").strip().casefold()
    return raw_query in raw_value or _normalise(query) in _normalise(value)


def _mask(value):
    text = str(value or "")
    if len(text) <= 4:
        return "＊" * len(text)
    return f"{text[:2]}{'＊' * (len(text) - 4)}{text[-2:]}"


def _display_value(instance, field):
    value = getattr(instance, field.name)
    if isinstance(field, models.FileField):
        return PurePath(value.name).name if value else ""
    if field.choices:
        return getattr(instance, f"get_{field.name}_display")()
    if isinstance(field, models.BooleanField):
        return "是" if value else "否"
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y/%m/%d %H:%M") if hasattr(value, "hour") else value.strftime("%Y/%m/%d")
    return str(value)


def _order_fields():
    return [
        field
        for field in SalesOrder._meta.fields
        if field.name not in INTERNAL_FIELDS
        and not isinstance(field, models.ForeignKey)
        and isinstance(field, SEARCHABLE_TYPES)
    ]


def build_order_search_query(query):
    # search_text 與查詢字串都已 casefold；使用 contains 才能讓 PostgreSQL
    # 直接採用 search_text 的 gin_trgm_ops index，避免 UPPER() 使索引失效。
    return Q(search_index__search_text__contains=_normalise(query))


def _append_match(matches, label, value, sensitive=False):
    shown = _mask(value) if sensitive else str(value)
    item = {"label": str(label), "value": shown}
    if item not in matches:
        matches.append(item)


def build_order_match_summary(order, query):
    cached = getattr(getattr(order, "search_index", None), "match_payload", None)
    if cached is not None:
        return [
            {
                "label": item["label"],
                "value": _mask(item["value"]) if item.get("sensitive") else item["value"],
            }
            for item in cached
            if _contains(item.get("value", ""), query)
        ]
    matches = []
    for field in _order_fields():
        raw_value = getattr(order, field.name)
        display_value = _display_value(order, field)
        values = [display_value]
        if field.choices:
            values.append(raw_value)
        if any(_contains(value, query) for value in values):
            _append_match(
                matches,
                field.verbose_name,
                display_value,
                field.name in SENSITIVE_FIELDS,
            )

    related_values = (
        ("來源名稱", getattr(order.source, "name", "")),
        ("廠牌", order.vehicle_model.brand),
        ("車型", order.vehicle_model.name),
        ("型號", order.vehicle_model.model_number),
        ("動力類型", order.vehicle_model.get_energy_type_display()),
        ("排氣量", order.vehicle_model.displacement_cc),
        ("車色", order.color.name),
    )
    vehicle = order.allocated_vehicle
    if vehicle:
        related_values += (
            ("引擎號碼", vehicle.engine_number),
            ("車身號碼", vehicle.frame_number),
            ("目前位置", vehicle.location_store.name),
            ("車況說明", vehicle.condition_note),
            ("車況處理結果", vehicle.condition_resolution),
            ("進車日期", vehicle.received_on),
            ("庫存狀態", vehicle.get_status_display()),
        )
    for label, value in related_values:
        if value not in (None, "") and _contains(value, query):
            _append_match(matches, label, value)

    profile = getattr(order, "operations", None)
    if profile:
        for field in profile._meta.fields:
            if field.name in {
                "id", "order", "created_at", "updated_at",
                "vehicle_control_password_encrypted",
                "battery_password_encrypted",
            }:
                continue
            value = _display_value(profile, field)
            if value not in (None, "") and _contains(value, query):
                _append_match(matches, field.verbose_name, value)

    collections = (
        (
            order.accessories.all(),
            (
                ("配件名稱", "name"),
                ("配件數量", "quantity"),
                ("配件類型", "get_line_type_display"),
                ("配件售價", "amount"),
                ("配件工資", "labor_fee"),
                ("配件備註", "note"),
            ),
        ),
        (
            order.other_fees.all(),
            (("其他費用項目", "name"), ("其他費用金額", "amount")),
        ),
        (
            order.subsidy_documents.all(),
            (
                ("補助文件類型", "get_document_type_display"),
                ("補助文件名稱", "name"),
                ("補助文件備註", "note"),
                ("補助文件檔名", "file"),
                ("補助文件上傳人員", "uploaded_by"),
            ),
        ),
        (
            order.registration_documents.all(),
            (
                ("領牌文件類型", "get_document_type_display"),
                ("領牌文件名稱", "name"),
                ("領牌文件檔名", "file"),
                ("領牌文件上傳人員", "uploaded_by"),
            ),
        ),
        (
            order.events.all(),
            (
                ("處理紀錄類型", "event_type"),
                ("處理紀錄內容", "description"),
                ("處理人員", "actor_name"),
            ),
        ),
        (
            order.changes.all(),
            (
                ("訂單變更原因", "reason"),
                ("訂單修改人員", "actor_name"),
            ),
        ),
        (
            order.payment_records.all(),
            (
                ("收款項目", "item_name"),
                ("應收金額", "expected_amount"),
                ("實收金額", "received_amount"),
                ("收款日期", "received_on"),
                ("收款方式", "payment_method"),
                ("收款帳戶", "receiving_account"),
                ("收款確認人員", "confirmed_by"),
                ("收款備註", "note"),
            ),
        ),
        (
            order.subsidy_items.all(),
            (("補助類別", "get_category_display"), ("補助項目", "item_name"), ("補助預計金額", "expected_amount"), ("補助申請日期", "applied_on"), ("補助狀態", "get_status_display"), ("補助備註", "note")),
        ),
    )
    for objects, fields in collections:
        for obj in objects:
            for label, attribute in fields:
                value = getattr(obj, attribute)
                value = value() if callable(value) else value
                if isinstance(value, models.fields.files.FieldFile):
                    value = PurePath(value.name).name if value else ""
                if value not in (None, "") and _contains(value, query):
                    _append_match(matches, label, value)
    return matches


def _index_item(items, label, value, sensitive=False):
    if isinstance(value, models.fields.files.FieldFile):
        value = PurePath(value.name).name if value else ""
    if value in (None, ""):
        return
    text = str(value)
    item = {"label": str(label), "value": text, "sensitive": bool(sensitive)}
    if item not in items:
        items.append(item)


def build_order_search_payload(order):
    items = []
    for field in _order_fields():
        raw_value = getattr(order, field.name)
        _index_item(
            items,
            field.verbose_name,
            _display_value(order, field),
            field.name in SENSITIVE_FIELDS,
        )
        if field.choices:
            _index_item(items, field.verbose_name, raw_value, field.name in SENSITIVE_FIELDS)

    related_values = (
        ("來源名稱", getattr(order.source, "name", "")),
        ("廠牌", order.vehicle_model.brand),
        ("車型", order.vehicle_model.name),
        ("型號", order.vehicle_model.model_number),
        ("動力類型", order.vehicle_model.get_energy_type_display()),
        ("排氣量", order.vehicle_model.displacement_cc),
        ("車色", order.color.name),
    )
    vehicle = order.allocated_vehicle
    if vehicle:
        related_values += (
            ("引擎號碼", vehicle.engine_number),
            ("車身號碼", vehicle.frame_number),
            ("目前位置", vehicle.location_store.name),
            ("車況說明", vehicle.condition_note),
            ("車況處理結果", vehicle.condition_resolution),
            ("進車日期", vehicle.received_on),
            ("庫存狀態", vehicle.get_status_display()),
        )
    for label, value in related_values:
        _index_item(items, label, value)

    legacy = getattr(order, "legacy_snapshot", None)
    if legacy:
        _index_item(items, "歷史引擎／車身號碼", legacy.vehicle_identifier)
        _index_item(items, "歷史收款價", legacy.historical_received_price)
        _index_item(items, "歷史現金收款", legacy.cash_received)
        _index_item(items, "歷史刷卡收款", legacy.card_received)
        _index_item(items, "銷售方案分類", legacy.sales_category)
        for label, value in legacy.raw_financials.items():
            _index_item(items, label, value)

    profile = getattr(order, "operations", None)
    if profile:
        for field in profile._meta.fields:
            if field.name in {
                "id", "order", "created_at", "updated_at",
                "vehicle_control_password_encrypted",
                "battery_password_encrypted",
            }:
                continue
            _index_item(items, field.verbose_name, _display_value(profile, field))

    collections = (
        (order.accessories.all(), (
            ("配件名稱", "name"), ("配件數量", "quantity"),
            ("配件類型", "get_line_type_display"), ("配件售價", "amount"),
            ("配件工資", "labor_fee"), ("配件備註", "note"),
        )),
        (order.other_fees.all(), (
            ("其他費用項目", "name"), ("其他費用金額", "amount"),
        )),
        (order.subsidy_documents.all(), (
            ("補助文件類型", "get_document_type_display"), ("補助文件名稱", "name"),
            ("補助文件備註", "note"), ("補助文件檔名", "file"),
            ("補助文件上傳人員", "uploaded_by"),
        )),
        (order.registration_documents.all(), (
            ("領牌文件類型", "get_document_type_display"), ("領牌文件名稱", "name"),
            ("領牌文件檔名", "file"), ("領牌文件上傳人員", "uploaded_by"),
        )),
        (order.events.all(), (
            ("處理紀錄類型", "event_type"), ("處理紀錄內容", "description"),
            ("處理人員", "actor_name"),
        )),
        (order.changes.all(), (
            ("訂單變更原因", "reason"), ("訂單修改人員", "actor_name"),
        )),
        (order.payment_records.all(), (
            ("收款項目", "item_name"), ("應收金額", "expected_amount"),
            ("實收金額", "received_amount"), ("收款日期", "received_on"),
            ("收款方式", "payment_method"), ("收款帳戶", "receiving_account"),
            ("收款確認人員", "confirmed_by"), ("收款備註", "note"),
        )),
        (order.subsidy_items.all(), (
            ("補助類別", "get_category_display"), ("補助項目", "item_name"),
            ("補助預計金額", "expected_amount"), ("補助申請日期", "applied_on"),
            ("補助狀態", "get_status_display"), ("補助備註", "note"),
        )),
    )
    for objects, fields in collections:
        for obj in objects:
            for label, attribute in fields:
                value = getattr(obj, attribute)
                _index_item(items, label, value() if callable(value) else value)
    return items


def rebuild_order_search_index(order_id):
    order = SalesOrder.objects.select_related(
        "source", "vehicle_model", "color", "allocated_vehicle", "operations", "legacy_snapshot",
        "allocated_vehicle__location_store",
    ).prefetch_related(
        "accessories", "other_fees", "subsidy_documents",
        "registration_documents", "events", "changes", "payment_records", "subsidy_items",
    ).filter(pk=order_id).first()
    if not order:
        return
    payload = build_order_search_payload(order)
    search_text = "\n".join(
        {_normalise(item["value"]) for item in payload if item.get("value")}
    )
    SalesOrderSearchIndex.objects.update_or_create(
        order=order,
        defaults={"search_text": search_text, "match_payload": payload},
    )


def schedule_order_search_rebuild(order_id):
    if not settings.REDIS_URL:
        rebuild_order_search_index(order_id)
        return

    transaction.on_commit(
        lambda: django_rq.get_queue("search").enqueue(
            rebuild_order_search_index,
            order_id,
            job_timeout=90,
            result_ttl=300,
            failure_ttl=86400,
        )
    )
