from pathlib import PurePath

from django.db import models
from django.db.models import Q

from sales.models import (
    AccessoryLine,
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
    ("vehicle_model__energy_type", "動力類型"),
    ("vehicle_model__displacement_cc", "排氣量"),
    ("color__name", "車色"),
    ("allocated_vehicle__engine_number", "引擎號碼"),
    ("allocated_vehicle__frame_number", "車身號碼"),
    ("allocated_vehicle__ownership_store__name", "庫存歸屬"),
    ("allocated_vehicle__location_store__name", "目前位置"),
    ("allocated_vehicle__condition_note", "車況說明"),
    ("allocated_vehicle__condition_resolution", "車況處理結果"),
    ("allocated_vehicle__received_on", "進車日期"),
    ("allocated_vehicle__status", "庫存狀態"),
    ("accessories__name", "配件名稱"),
    ("accessories__quantity", "配件數量"),
    ("accessories__line_type", "配件類型"),
    ("accessories__amount", "配件金額"),
    ("accessories__installed_on", "配件安裝日期"),
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
    return Q(search_index__search_text__icontains=_normalise(query))


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
        ("動力類型", order.vehicle_model.get_energy_type_display()),
        ("排氣量", order.vehicle_model.displacement_cc),
        ("車色", order.color.name),
    )
    vehicle = order.allocated_vehicle
    if vehicle:
        related_values += (
            ("引擎號碼", vehicle.engine_number),
            ("車身號碼", vehicle.frame_number),
            ("庫存歸屬", vehicle.ownership_store.name),
            ("目前位置", vehicle.location_store.name),
            ("車況說明", vehicle.condition_note),
            ("車況處理結果", vehicle.condition_resolution),
            ("進車日期", vehicle.received_on),
            ("庫存狀態", vehicle.get_status_display()),
        )
    for label, value in related_values:
        if value not in (None, "") and _contains(value, query):
            _append_match(matches, label, value)

    collections = (
        (
            order.accessories.all(),
            (
                ("配件名稱", "name"),
                ("配件數量", "quantity"),
                ("配件類型", "get_line_type_display"),
                ("配件金額", "amount"),
                ("配件安裝日期", "installed_on"),
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
        ("動力類型", order.vehicle_model.get_energy_type_display()),
        ("排氣量", order.vehicle_model.displacement_cc),
        ("車色", order.color.name),
    )
    vehicle = order.allocated_vehicle
    if vehicle:
        related_values += (
            ("引擎號碼", vehicle.engine_number),
            ("車身號碼", vehicle.frame_number),
            ("庫存歸屬", vehicle.ownership_store.name),
            ("目前位置", vehicle.location_store.name),
            ("車況說明", vehicle.condition_note),
            ("車況處理結果", vehicle.condition_resolution),
            ("進車日期", vehicle.received_on),
            ("庫存狀態", vehicle.get_status_display()),
        )
    for label, value in related_values:
        _index_item(items, label, value)

    collections = (
        (order.accessories.all(), (
            ("配件名稱", "name"), ("配件數量", "quantity"),
            ("配件類型", "get_line_type_display"), ("配件金額", "amount"),
            ("配件安裝日期", "installed_on"), ("配件備註", "note"),
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
    )
    for objects, fields in collections:
        for obj in objects:
            for label, attribute in fields:
                value = getattr(obj, attribute)
                _index_item(items, label, value() if callable(value) else value)
    return items


def rebuild_order_search_index(order_id):
    order = SalesOrder.objects.select_related(
        "source", "vehicle_model", "color", "allocated_vehicle",
        "allocated_vehicle__ownership_store", "allocated_vehicle__location_store",
    ).prefetch_related(
        "accessories", "other_fees", "subsidy_documents",
        "registration_documents", "events", "changes",
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
    # 索引與業務資料使用同一個 transaction，失敗時會一起回滾。
    # 同步更新可避免剛儲存後立刻搜尋卻查不到；索引內容只讀單一訂單，
    # 不會重現舊版跨全表 JOIN 的負載。
    rebuild_order_search_index(order_id)
