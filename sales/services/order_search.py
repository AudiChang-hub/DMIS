import logging
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
from sales.services.vehicle_brands import vehicle_brand_search_names
from sales.templatetags.compact_text import compact_value


logger = logging.getLogger(__name__)


INTERNAL_FIELDS = {
    "id",
    "revision",
    "editing_session",
    "editing_at",
}
# 只供搜尋、不在命中摘要顯示內容的欄位（T-257 優惠備註：搜得到這張單，但結果列表不露出備註文字）。
SEARCH_ONLY_FIELDS = {"discount_internal_note"}
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
    ("vehicle_model__family__name", "機種"),
    ("vehicle_model__name", "車型"),
    ("vehicle_model__model_number", "型號"),
    ("vehicle_model__factory_model_codes__code", "原廠型號"),
    ("vehicle_model__model_year", "年份"),
    ("vehicle_model__model_code", "型式"),
    ("vehicle_model__energy_type", "動力類型"),
    ("vehicle_model__displacement_cc", "排氣量"),
    ("price_version__suggested_price", "分期總價"),
    ("price_version__cash_price", "現金價"),
    ("color__name", "車色"),
    ("allocated_vehicle__engine_number", "引擎號碼"),
    ("allocated_vehicle__frame_number", "車身號碼"),
    ("allocated_vehicle__current_dealer__name", "目前位置"),
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
    ("operations__battery_rate_plan", "交車前確認備註"),
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


def _factory_model_code_text(vehicle_model):
    codes = list(
        vehicle_model.factory_model_codes.filter(active=True)
        .order_by("code")
        .values_list("code", flat=True)
    )
    return "、".join(codes)


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


def build_order_search_query(query, *, profit_unlocked=True):
    # search_text 與查詢字串都已 casefold；使用 contains 才能讓 PostgreSQL
    # 直接採用 search_text 的 gin_trgm_ops index，避免 UPPER() 使索引失效。
    terms = {_normalise(query)}
    terms.update(_normalise(name) for name in vehicle_brand_search_names(query))
    result = Q()
    for term in terms:
        if term:
            lookup = "search_index__search_text__contains" if profit_unlocked else "search_index__safe_search_text__contains"
            result |= Q(**{lookup: term})
    return result


def _append_match(matches, label, value, sensitive=False):
    # 證件號碼完整顯示（2026-10-15 起只有店內人員使用，取消遮罩）；sensitive 參數保留給既有呼叫端。
    item = {"label": str(label), "value": str(value)}
    if item not in matches:
        matches.append(item)


def order_match_terms(query):
    """全部訂單一頁共用的搜尋詞（查詢字串＋品牌別名）；整頁只算一次，不逐列查品牌（T-281）。"""
    return [query, *vehicle_brand_search_names(query)]


def _contains_any(value, terms):
    """與 any(_contains(value, term) for term in terms) 相同，但 value 只正規化一次（T-281）。"""
    raw_value = str(value or "").casefold()
    normalised_value = None
    for raw_query, normalised_query in terms:
        if raw_query in raw_value:
            return True
        if normalised_value is None:
            normalised_value = _normalise(value)
        if normalised_query in normalised_value:
            return True
    return False


def build_order_match_summary(order, query, *, profit_unlocked=True, search_terms=None):
    search_terms = order_match_terms(query) if search_terms is None else search_terms
    cached = getattr(getattr(order, "search_index", None), "match_payload" if profit_unlocked else "safe_match_payload", None)
    if cached is None and not profit_unlocked:
        cached = build_order_search_payload(order, include_private=False)
    if cached is not None:
        prepared = [(str(term or "").strip().casefold(), _normalise(term)) for term in search_terms]
        return [
            {
                "label": item["label"],
                "value": item["value"],
            }
            for item in cached
            if not item.get("search_only")
            and _contains_any(item.get("value", ""), prepared)
        ]
    matches = []
    for field in _order_fields():
        if field.name in SEARCH_ONLY_FIELDS:
            continue
        raw_value = getattr(order, field.name)
        display_value = _display_value(order, field)
        values = [display_value]
        if field.choices:
            values.append(raw_value)
        if any(_contains(value, term) for value in values for term in search_terms):
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
        ("原廠型號", _factory_model_code_text(order.vehicle_model)),
        ("動力類型", order.vehicle_model.get_energy_type_display()),
        ("排氣量", order.vehicle_model.displacement_cc),
        ("車色", order.color.label),
    )
    vehicle = order.allocated_vehicle
    if vehicle:
        related_values += (
            ("引擎號碼", vehicle.engine_number),
            ("車身號碼", vehicle.frame_number),
            ("目前位置", vehicle.whereabouts_label),
            ("車況說明", vehicle.condition_note),
            ("車況處理結果", vehicle.condition_resolution),
            ("進車日期", vehicle.received_on),
            ("庫存狀態", vehicle.get_status_display()),
        )
    for label, value in related_values:
        if value not in (None, "") and any(
            _contains(value, term) for term in search_terms
        ):
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


# ---- T-319：結果列「符合欄位」提示只列短摘要（搜尋範圍與結果筆數不變，只改顯示）----
# 全部訂單每一列已經看得到的欄位：符合時不另列（車主姓名、訂單編號、車牌、兩個日期、引擎／車身號碼、車色、車行）。
# 備註在列上只顯示前幾個字，符合處可能看不到，所以照樣列出摘要。
ROW_VISIBLE_LABELS = frozenset({
    "車主姓名／公司名稱", "訂單編號", "最終車牌號碼", "訂單成立日期", "實際領牌日期",
    "引擎號碼", "車身號碼", "車色", "來源名稱",
})
# T-326：列上的機種會截成這個字數（同 order_list.html／_order_row.html 的
# _compact_text limit）。車型只有在關鍵字落在截掉的那段、列上看不到時才列提示。
ROW_MACHINE_LIMIT = 10
# 系統稽核資料：只供日後核對，不出現在結果列。
AUDIT_LABEL_MARKERS = ("內容指紋", "SHA-256")
AUDIT_SEGMENT_PREFIXES = ("IP：", "裝置：", "內容指紋：", "檔案 SHA-256：")
MATCH_HINT_LIMIT = 2
SNIPPET_BEFORE = 8
SNIPPET_AFTER = 12
_NORMALISE_DROPPED = frozenset(" -/／")


def _strip_audit_segments(text):
    """電子簽署紀錄的 IP、裝置字串、內容指紋、檔案 SHA-256 一段段拿掉，只留給人看的說明。"""
    segments = str(text or "").split("；")
    kept = [segment for segment in segments if not segment.strip().startswith(AUDIT_SEGMENT_PREFIXES)]
    return "；".join(kept)


def _locate_term(text, prepared_terms):
    """回傳 text 中第一個符合的 (start, end)，比對規則與 _contains 相同（不分大小寫、忽略空白與連字號）。"""
    for drop in (frozenset(), _NORMALISE_DROPPED):
        folded, positions = [], []
        for index, char in enumerate(text):
            if char in drop:
                continue
            for folded_char in char.casefold():
                folded.append(folded_char)
                positions.append(index)
        haystack = "".join(folded)
        for raw_query, normalised_query in prepared_terms:
            needle = normalised_query if drop else raw_query
            if not needle:
                continue
            found = haystack.find(needle)
            if found >= 0:
                return positions[found], positions[found + len(needle) - 1] + 1
    return None


def _snippet(label, text, prepared_terms):
    span = _locate_term(text, prepared_terms)
    if span is None:  # 品牌別名等間接符合：值本身沒有關鍵字，整段截短後標色
        limit = SNIPPET_BEFORE + SNIPPET_AFTER
        hit = text if len(text) <= limit else text[:limit] + "…"
        return {"label": label, "before": "", "hit": hit, "after": ""}
    start, end = span
    before_start = max(0, start - SNIPPET_BEFORE)
    after_end = min(len(text), end + SNIPPET_AFTER)
    before = ("…" if before_start else "") + text[before_start:start]
    after = text[end:after_end] + ("…" if after_end < len(text) else "")
    # 結果列只標 hit（關鍵字），before／after 是前後文，不標色。
    return {"label": label, "before": before, "hit": text[start:end], "after": after}


def _row_machine_preview(model_name):
    """列上機種欄截短後看得到的文字（不含「…」）。

    列上顯示所屬機種名稱；車型存檔時會依名稱連到同名機種（VehicleModel.save），兩者相同，直接用車型名稱比對。
    """
    compact = compact_value(model_name, ROW_MACHINE_LIMIT)
    return compact["preview"].removesuffix("…") if compact["shortened"] else model_name


def condense_order_matches(order, matches, search_terms):
    """把 build_order_match_summary 的完整符合清單整理成結果列要顯示的提示。

    回傳 (最多 MATCH_HINT_LIMIT 項的摘要, 其餘符合的欄位數)。該列已顯示的欄位、與姓名／編號／車牌同值的欄位、
    系統稽核資料都不列；同一欄位只列一次；每項只留符合處前後一小段。
    """
    prepared = [(str(term or "").strip().casefold(), _normalise(term)) for term in search_terms]
    visible_values = {
        _normalise(value) for value in (order.owner_name, order.number, order.final_plate_number) if value
    }
    shown, extra_labels, seen = [], set(), set()
    for item in matches:
        label = item["label"]
        if label in seen or label in ROW_VISIBLE_LABELS or any(marker in label for marker in AUDIT_LABEL_MARKERS):
            continue
        text = " ".join(_strip_audit_segments(item["value"]).split())
        if not text or not _contains_any(text, prepared) or _normalise(text) in visible_values:
            continue
        if label == "車型" and _locate_term(_row_machine_preview(text), prepared) is not None:
            continue  # 關鍵字在列上的機種裡看得到
        seen.add(label)
        if len(shown) < MATCH_HINT_LIMIT:
            snippet = _snippet(label, text, prepared)
            # 機種只有表格在 1440 寬以下才截短；手機卡片、寬螢幕顯示全名，畫面上用 CSS 藏起來（order-list.css）。
            snippet["compact_only"] = label == "車型"
            shown.append(snippet)
        else:
            extra_labels.add(label)
    return shown, len(extra_labels)


def _index_item(items, label, value, sensitive=False, *, private=False, search_only=False):
    if isinstance(value, models.fields.files.FieldFile):
        value = PurePath(value.name).name if value else ""
    if value in (None, ""):
        return
    text = str(value)
    item = {"label": str(label), "value": text, "sensitive": bool(sensitive)}
    if private:
        item["profit_private"] = True
    if search_only:
        item["search_only"] = True
    if item not in items:
        items.append(item)


def build_order_search_payload(order, *, include_private=True):
    items = []
    for field in _order_fields():
        raw_value = getattr(order, field.name)
        _index_item(
            items,
            field.verbose_name,
            _display_value(order, field),
            field.name in SENSITIVE_FIELDS,
            search_only=field.name in SEARCH_ONLY_FIELDS,
        )
        if field.choices:
            _index_item(items, field.verbose_name, raw_value, field.name in SENSITIVE_FIELDS)

    related_values = (
        ("來源名稱", getattr(order.source, "name", "")),
        ("廠牌", order.vehicle_model.brand),
        ("車型", order.vehicle_model.name),
        ("型號", order.vehicle_model.model_number),
        ("原廠型號", _factory_model_code_text(order.vehicle_model)),
        ("動力類型", order.vehicle_model.get_energy_type_display()),
        ("排氣量", order.vehicle_model.displacement_cc),
        ("車色", order.color.label),
    )
    vehicle = order.allocated_vehicle
    if vehicle:
        related_values += (
            ("引擎號碼", vehicle.engine_number),
            ("車身號碼", vehicle.frame_number),
            ("目前位置", vehicle.whereabouts_label),
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
        for label, value in (legacy.raw_financials.items() if include_private else ()):
            _index_item(items, label, value, private=True)

    profile = getattr(order, "operations", None)
    if profile:
        for field in profile._meta.fields:
            if not include_private and isinstance(field, models.JSONField):
                continue  # 財務核對 JSON 可能包含原始／核對後淨利。
            if field.name in {
                "id", "order", "created_at", "updated_at",
                "vehicle_control_password_encrypted",
                "battery_password_encrypted",
            }:
                continue
            _index_item(items, field.verbose_name, _display_value(profile, field), private=isinstance(field, models.JSONField))

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
        "allocated_vehicle__current_dealer",
    ).prefetch_related(
        "vehicle_model__factory_model_codes", "accessories", "other_fees", "subsidy_documents",
        "registration_documents", "events", "changes", "payment_records", "subsidy_items",
    ).filter(pk=order_id).first()
    if not order:
        return
    payload = build_order_search_payload(order)
    safe_payload = [item for item in payload if not item.get("profit_private")]
    search_text = "\n".join(
        {_normalise(item["value"]) for item in payload if item.get("value")}
    )
    SalesOrderSearchIndex.objects.update_or_create(
        order=order,
        defaults={"search_text": search_text, "match_payload": payload,
                  "safe_search_text": "\n".join({_normalise(item["value"]) for item in safe_payload if item.get("value")}),
                  "safe_match_payload": safe_payload},
    )


def schedule_order_search_rebuild(order_id):
    if not settings.REDIS_URL:
        rebuild_order_search_index(order_id)
        return

    def enqueue_or_rebuild():
        try:
            django_rq.get_queue("search").enqueue(
                rebuild_order_search_index,
                order_id,
                job_timeout=90,
                result_ttl=300,
                failure_ttl=86400,
            )
        except Exception:
            logger.exception(
                "搜尋索引無法排入背景佇列，改用同步重建",
                extra={"order_id": order_id},
            )
            try:
                rebuild_order_search_index(order_id)
            except Exception:
                # 索引屬於衍生資料；即使降級重建也失敗，不應讓已提交的
                # 訂單操作回傳 500。保留完整日誌供管理者後續重建。
                logger.exception(
                    "搜尋索引同步降級重建失敗",
                    extra={"order_id": order_id},
                )

    transaction.on_commit(enqueue_or_rebuild)
