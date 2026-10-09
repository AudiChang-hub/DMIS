"""銷貨匯入與既有訂單比對：疑似重複、號碼已屬他人與匯入後 Excel 改動。

匯入以交易鍵（車輛識別＋類別＋日期＋車主）判斷是否已匯入；Excel 更正號碼或車主時交易鍵改變，
會被當成新交易而重複建單，交易鍵相同但其他欄位改過則整列略過。本模組在預覽時找出三種情況：

- SAME_OWNER：同車主、同型號、同日期，但車輛識別不同（可能是同一筆交易更正了號碼）。
- IDENTIFIER_TAKEN：新車號碼已用在另一位車主的訂單（可能是號碼或車主填錯）。
- CHANGED：交易鍵相同、已匯入，但 Excel 有欄位與第一次匯入時不同。

使用者可決定排除、仍新增，或用 Excel 更新既有訂單。更新只套用勾選且「系統值仍等於上次匯入值」的欄位
（匯入後在系統改過的欄位不覆蓋）；Excel 清空的欄位預設不清除，需另外勾選。領牌日期、型號、來源與金額只顯示差異，
不從這裡更新。號碼已屬他人（IDENTIFIER_TAKEN）不提供更新：不可直接把原訂單改成新買家，只能排除或仍新增。
"""
from datetime import date

from django.db import transaction
from django.utils import timezone

from sales.models import (
    LegacyImportBatch,
    LegacyImportCorrection,
    LegacyImportRow,
    LegacySalesSnapshot,
    OrderChange,
    OrderEvent,
    SalesOrder,
    normalize_vehicle_identifier,
    normalize_vehicle_model_master_value,
)

SAME_OWNER = "same_owner"
IDENTIFIER_TAKEN = "identifier_taken"
CHANGED = "changed"
KIND_TITLES = {
    SAME_OWNER: "疑似重複：同車主、同型號、同日期，但車輛識別不同",
    IDENTIFIER_TAKEN: "疑似號碼錯誤：此新車號碼已用在另一位車主的訂單",
    CHANGED: "已匯入，但 Excel 有改動",
}
SAME_OWNER_MESSAGE = "疑似重複：與已匯入訂單同車主、同型號、同日期，但車輛識別不同；請到「既有訂單比對」選擇排除、仍新增或更新既有訂單"
IDENTIFIER_TAKEN_MESSAGE = "疑似號碼錯誤：此新車號碼已用在另一位車主的已匯入訂單；請到「既有訂單比對」選擇排除、仍新增或更新既有訂單"
CHANGED_MESSAGE = "已匯入但 Excel 有改動：可到「既有訂單比對」用 Excel 更新既有訂單，或維持略過"
REVIEW_MESSAGES = {SAME_OWNER_MESSAGE, IDENTIFIER_TAKEN_MESSAGE, CHANGED_MESSAGE}
KIND_MESSAGES = {SAME_OWNER: SAME_OWNER_MESSAGE, IDENTIFIER_TAKEN: IDENTIFIER_TAKEN_MESSAGE, CHANGED: CHANGED_MESSAGE}
EVENT = "legacy_import_update"

# (Excel 欄位, 名稱, 可從 Excel 更新)
FIELDS = (
    ("identifier_raw", "車輛識別（引擎／車身號碼）", True),
    ("owner_name", "車主姓名", True),
    ("owner_id_number", "車主身分證號", True),
    ("owner_phone", "車主電話", True),
    ("owner_address", "車主地址", True),
    ("owner_email", "Email", True),
    ("owner_birth_date", "車主生日", True),
    ("plate_number", "車牌", True),
    ("invoice_date", "發票日期", True),
    ("trade_in_plate", "汰舊舊車牌", True),
    ("old_owner_name", "舊車主姓名", True),
    ("old_owner_id_number", "舊車主身分證號", True),
    ("old_vehicle_engine_number", "舊車引擎號碼", True),
    ("old_vehicle_brand", "舊車廠牌", True),
    ("registration_date", "領牌日期", False),
    ("model_number", "車種型號", False),
    ("dealer_name", "來源（車行／平台）", False),
    ("color", "顏色", False),
    ("installment_periods", "分期期數", False),
    ("cash_received", "現金收款", False),
    ("card_received", "刷卡收款", False),
)
FIELD_LABELS = {key: label for key, label, _updatable in FIELDS}
UPDATABLE = {key for key, _label, updatable in FIELDS if updatable}
PLACEHOLDERS = {"歷史資料未填", "未提供"}
UPPER_FIELDS = {"plate_number", "trade_in_plate", "owner_id_number", "old_owner_id_number"}
UPDATE_STATES = {"update", "clear"}
# 系統必填或有佔位值的欄位不允許清空。
NOT_CLEARABLE = {"owner_name", "owner_id_number", "owner_phone", "owner_address"}


def _text(value):
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    return " ".join(str(value).split())


def _norm(key, value):
    text = _text(value)
    if key == "identifier_raw":
        return normalize_vehicle_identifier(text) or ""
    if text in PLACEHOLDERS or (key == "owner_id_number" and text.upper().startswith("HIST-")):
        return ""
    if key in {"cash_received", "card_received", "installment_periods"}:
        try:
            return str(int(float(text.replace(",", "")))) if text else "0"
        except ValueError:
            return text
    if key == "model_number":
        return normalize_vehicle_model_master_value(text) if text else ""
    return text.upper() if key in UPPER_FIELDS else text


def _excel(data, key):
    if key == "identifier_raw":
        return data.get("identifier_raw") or data.get("identifier") or ""
    return data.get(key)


def _owner_identity(data):
    owner_id = _text(data.get("owner_id_number")).upper()
    if owner_id and not owner_id.startswith("HIST-"):
        return f"id:{owner_id}"
    name = _text(data.get("owner_name"))
    return f"name:{name}" if name and name not in PLACEHOLDERS else ""


def _transaction_day(data):
    return _text(data.get("registration_date") or data.get("invoice_date") or data.get("order_date"))


def _transaction_key(data):
    from sales.services.legacy_import import _sales_transaction_key
    return _sales_transaction_key(data)


def completed_sales_keys():
    """與匯入預覽相同口徑：已完成批次中新增／更新／略過的銷貨列，重算交易鍵。"""
    rows = LegacyImportRow.objects.filter(
        sheet_name="銷貨", batch__status=LegacyImportBatch.Status.COMPLETED,
        action__in=[LegacyImportRow.Action.CREATE, LegacyImportRow.Action.UPDATE, LegacyImportRow.Action.SKIP],
    ).values_list("mapped_data", flat=True)
    return {_transaction_key(data) for data in rows}


def _system_value(order, key):
    """訂單目前值（只讀）。"""
    profile = getattr(order, "operations", None)
    snapshot = getattr(order, "legacy_snapshot", None)
    if key == "identifier_raw":
        vehicle = order.allocated_vehicle
        if vehicle:
            return vehicle.engine_number or vehicle.frame_number or ""
        return snapshot.vehicle_identifier if snapshot else ""
    if key == "plate_number":
        return order.final_plate_number
    if key in {"invoice_date", "old_vehicle_engine_number", "old_vehicle_brand"}:
        return getattr(profile, key, "") if profile else ""
    if key in {"owner_name", "owner_id_number", "owner_phone", "owner_address", "owner_email", "owner_birth_date",
               "trade_in_plate", "old_owner_name", "old_owner_id_number", "registration_date"}:
        return getattr(order, key)
    return None  # 只與上次匯入值比對的欄位


class ImportedOrders:
    """已匯入且仍存在的訂單，以及每張訂單「目前採用的匯入內容」（第一次匯入，疊加之後由 Excel 更新的欄位）。"""

    def __init__(self, order_ids=None):
        snapshots = LegacySalesSnapshot.objects.select_related("import_row")
        if order_ids is not None:
            snapshots = snapshots.filter(order_id__in=order_ids)
        self.orders = {
            order.pk: order for order in SalesOrder.objects.select_related("operations", "legacy_snapshot", "allocated_vehicle")
            .filter(pk__in=[s.order_id for s in snapshots])
        }
        live = set(self.orders)
        self.baseline = {}
        self.key_to_order = {}
        for snapshot in snapshots:
            if snapshot.order_id not in live:
                continue
            self.baseline[snapshot.order_id] = dict(snapshot.import_row.mapped_data or {})
            self.key_to_order[snapshot.import_row.natural_key] = snapshot.order_id
            self.key_to_order[_transaction_key(snapshot.import_row.mapped_data or {})] = snapshot.order_id
        updates = LegacyImportRow.objects.filter(
            sheet_name="銷貨", action=LegacyImportRow.Action.UPDATE, committed_model="SalesOrder",
            batch__status=LegacyImportBatch.Status.COMPLETED,
        ).select_related("batch").order_by("batch__confirmed_at", "pk")
        for row in updates:
            order_id = int(row.committed_pk) if str(row.committed_pk).isdigit() else None
            if order_id not in self.baseline:
                continue
            for key in (row.mapped_data.get("_review") or {}).get("fields", []):
                self.baseline[order_id][key] = row.mapped_data.get(key)
                if key == "identifier_raw":
                    self.baseline[order_id]["identifier"] = row.mapped_data.get("identifier")
            self.key_to_order[row.natural_key] = order_id
            self.key_to_order[_transaction_key(row.mapped_data or {})] = order_id
        self.by_owner = {}
        self.by_identifier = {}
        for order_id, data in self.baseline.items():
            triple = (_owner_identity(data), _norm("model_number", data.get("model_number")), _transaction_day(data))
            if triple[0] and triple[2]:
                self.by_owner.setdefault(triple, []).append(order_id)
            identifier = _norm("identifier_raw", _excel(data, "identifier_raw"))
            if identifier and (data.get("vehicle_category") or SalesOrder.VehicleCategory.NEW) == SalesOrder.VehicleCategory.NEW:
                self.by_identifier.setdefault(identifier, []).append(order_id)

    def candidates(self, data, natural_key):
        """新交易鍵的列：回傳 (類型, [訂單]) 或 None。"""
        triple = (_owner_identity(data), _norm("model_number", data.get("model_number")), _transaction_day(data))
        same_owner = [
            pk for pk in self.by_owner.get(triple, [])
            if _norm("identifier_raw", _excel(self.baseline[pk], "identifier_raw")) != _norm("identifier_raw", _excel(data, "identifier_raw"))
        ] if triple[0] and triple[2] else []
        if same_owner:
            return SAME_OWNER, sorted(same_owner)
        identifier = _norm("identifier_raw", _excel(data, "identifier_raw"))
        if identifier and (data.get("vehicle_category") or SalesOrder.VehicleCategory.NEW) == SalesOrder.VehicleCategory.NEW:
            others = [pk for pk in self.by_identifier.get(identifier, [])
                      if _owner_identity(self.baseline[pk]) != _owner_identity(data)]
            if others:
                return IDENTIFIER_TAKEN, sorted(others)
        return None


def field_states(data, order, baseline):
    """逐欄比對；state：update（可用 Excel 更新）、clear（Excel 已清空，可勾選一併清除）、system（匯入後系統改過，
    需人工判斷）、excel_blank（Excel 空白但不可清除）、info（只顯示差異，不從這裡更新）、locked（不可更新的情況）。"""
    rows = []
    for key, label, updatable in FIELDS:
        excel = _norm(key, _excel(data, key))
        previous = _norm(key, _excel(baseline, key))
        raw_system = _system_value(order, key)
        if raw_system is None or not updatable:
            # 只比對 Excel 與上次匯入值
            if excel == previous:
                continue
            state = "info"
            system_display = _text(raw_system) if raw_system is not None else ""
        else:
            system = _norm(key, raw_system)
            if excel == system:
                continue
            if system != previous:
                state = "system"
            elif not excel:
                state = "excel_blank" if key in NOT_CLEARABLE else "clear"
            else:
                state = "update"
            if state in UPDATE_STATES and key == "identifier_raw" and order.allocated_vehicle_id:
                state = "locked"
            if state == "update" and key == "trade_in_plate" and not system:
                state = "locked"  # 新增舊車牌會影響汰舊補助，請在訂單處理
            if state == "clear" and key == "trade_in_plate":
                state = "locked"  # 移除舊車牌會影響汰舊補助，請在訂單處理
            if state in UPDATE_STATES and key in {"old_owner_name", "old_owner_id_number"} and order.old_owner_same_as_owner:
                state = "locked"
            system_display = _text(raw_system)
        rows.append({
            "key": key, "label": label, "state": state, "excel_changed": excel != previous,
            "system": system_display, "excel": _text(_excel(data, key)), "previous": _text(_excel(baseline, key)),
        })
    return rows


def _load_order(pk):
    return SalesOrder.objects.select_related("operations", "legacy_snapshot", "allocated_vehicle").filter(pk=pk).first()


def classify(row, index, completed_keys):
    """revalidate 用：回傳 (類型, [訂單 pk]) 或 None。CHANGED 只在有差異欄位時回傳。"""
    data = row.mapped_data or {}
    if row.natural_key in completed_keys:
        order_id = index.key_to_order.get(row.natural_key)
        order = index.orders.get(order_id)
        # 只在 Excel 本身改過（與上次匯入不同）時提示；只在系統改過的欄位不重複提醒。
        if order and any(item["excel_changed"] for item in field_states(data, order, index.baseline[order_id])):
            return CHANGED, [order_id]
        return None
    return index.candidates(data, row.natural_key)


def valid_update(row, index, match):
    """「用 Excel 更新」的決定是否仍有效：訂單仍在候選內，且勾選欄位仍可更新。"""
    review = (row.mapped_data or {}).get("_review") or {}
    if review.get("decision") != "update" or not match or review.get("order") not in match[1]:
        return False
    if match[0] == IDENTIFIER_TAKEN:
        return False
    order = index.orders.get(review["order"])
    allowed = {item["key"] for item in field_states(row.mapped_data, order, index.baseline[order.pk]) if item["state"] in UPDATE_STATES}
    return bool(review.get("fields")) and set(review["fields"]) <= allowed


def row_reviews(rows):
    """預覽畫面：帶出每列的比對卡片（只處理有比對訊息的列）。"""
    rows = [row for row in rows if REVIEW_MESSAGES.intersection(row.messages or [])]
    if not rows:
        return []
    index = ImportedOrders()
    completed = completed_sales_keys()
    reviews = []
    for row in rows:
        result = classify(row, index, completed)
        if not result:
            continue
        kind, order_ids = result
        decision = (row.mapped_data or {}).get("_review") or {}
        cards = []
        for order_id in order_ids:
            order = index.orders.get(order_id)
            if order:
                cards.append({"order": order, "fields": field_states(row.mapped_data, order, index.baseline[order_id])})
        reviews.append({"row": row, "kind": kind, "title": KIND_TITLES[kind], "orders": cards, "decision": decision,
                        "can_update": kind != IDENTIFIER_TAKEN})
    return reviews


@transaction.atomic
def decide(row, *, decision, order_id=None, fields=(), reason="", actor_name=""):
    """記錄使用者對比對結果的決定：update（用 Excel 更新既有訂單）、create（仍新增）、keep（維持略過）、clear（取消決定）。"""
    from sales.services.legacy_import import revalidate_import_batch

    if row.batch.status != LegacyImportBatch.Status.PREVIEW:
        raise ValueError("只有待確認批次可以處理比對結果。")
    reason = _text(reason)
    if decision != "clear" and len(reason) < 2:
        raise ValueError("請填寫處理原因。")
    index = ImportedOrders()
    result = classify(row, index, completed_sales_keys())
    current = dict(row.mapped_data or {})
    before = dict(current)
    if decision == "clear":
        current.pop("_review", None)
    else:
        if not result:
            raise ValueError("這一列已沒有需要比對的既有訂單，請重新整理預覽。")
        kind, order_ids = result
        if decision == "create":
            if kind == CHANGED:
                raise ValueError("已匯入的列不能再新增一筆。")
            current["_review"] = {"decision": "create", "kind": kind, "orders": order_ids}
        elif decision == "keep":
            current.pop("_review", None)
        elif decision == "update":
            if kind == IDENTIFIER_TAKEN:
                raise ValueError("號碼已屬另一位車主的訂單，不能直接改成這位買家；請選擇排除或仍新增。")
            order_id = int(order_id) if str(order_id or "").isdigit() else None
            if order_id not in order_ids:
                raise ValueError("請選擇要更新的既有訂單。")
            order = index.orders[order_id]
            allowed = {item["key"] for item in field_states(current, order, index.baseline[order_id]) if item["state"] in UPDATE_STATES}
            chosen = [key for key in fields if key in allowed]
            if not chosen:
                raise ValueError("請勾選至少一個可從 Excel 更新的欄位。")
            current["_review"] = {"decision": "update", "kind": kind, "order": order_id, "fields": chosen}
        else:
            raise ValueError("不明的處理方式。")
        current["_review"].update({"by": actor_name, "at": timezone.now().isoformat(), "reason": reason})
    row.mapped_data = current
    row.manually_corrected = True
    row.corrected_by = actor_name
    row.corrected_at = timezone.now()
    row.save(update_fields=["mapped_data", "manually_corrected", "corrected_by", "corrected_at", "updated_at"])
    labels = {"update": "用 Excel 更新既有訂單", "create": "確認不同交易、仍新增", "keep": "維持略過", "clear": "取消比對決定"}
    LegacyImportCorrection.objects.create(
        row=row, decision=LegacyImportCorrection.Decision.CORRECT, before_data=before, after_data=current,
        reason=f"既有訂單比對：{labels[decision]}；{reason}".strip("；"), corrected_by=actor_name,
    )
    return revalidate_import_batch(row.batch)


def _apply(order, key, value):
    """把 Excel 值寫回訂單（呼叫端負責 save）。回傳實際寫入的物件。"""
    profile = order.operations
    snapshot = order.legacy_snapshot
    text = _text(value)
    if key == "identifier_raw":
        snapshot.vehicle_identifier = text
        return snapshot
    if key == "plate_number":
        order.final_plate_number = text.upper()
        return order
    if key in {"invoice_date", "owner_birth_date"}:
        from sales.services.legacy_import import _date
        target = profile if key == "invoice_date" else order
        setattr(target, key, _date(value))
        return target
    if key in {"old_vehicle_engine_number", "old_vehicle_brand"}:
        setattr(profile, key, text)
        return profile
    setattr(order, key, text.upper() if key in UPPER_FIELDS else text)
    return order


def commit_update(row, actor_name):
    """確認匯入時：依決定更新既有訂單；預覽後欄位被改過就整列失敗，請重新預覽。"""
    review = (row.mapped_data or {}).get("_review") or {}
    order_id = review.get("order")
    order = SalesOrder.objects.select_for_update(of=("self",)).filter(pk=order_id).first()
    if not order:
        raise ValueError("要更新的既有訂單已不存在，請重新預覽。")
    order = _load_order(order_id)
    index = ImportedOrders(order_ids=[order_id])
    if order_id not in index.baseline:
        raise ValueError("要更新的既有訂單沒有匯入快照，請重新預覽。")
    states = {item["key"]: item for item in field_states(row.mapped_data, order, index.baseline[order_id])}
    changes, touched = {}, {}
    for key in review.get("fields", []):
        item = states.get(key)
        if not item or item["state"] not in UPDATE_STATES:
            raise ValueError(f"訂單 {order.number} 的「{FIELD_LABELS.get(key, key)}」在預覽後已變動，請重新預覽後再確認。")
        changes[FIELD_LABELS[key]] = {"before": item["system"], "after": item["excel"] or "（清除）"}
        target = _apply(order, key, _excel(row.mapped_data, key))
        touched[id(target)] = target
    for target in touched.values():
        target.save()
    reason = review.get("reason", "")
    OrderChange.objects.create(order=order, reason=f"Excel 匯入更新（{row.sheet_name}第 {row.source_row} 列）；{reason}",
                               changes=changes, actor_name=actor_name)
    OrderEvent.objects.create(
        order=order, event_type=EVENT, actor_name=actor_name,
        description=f"來源列 {row.pk}（Excel 第 {row.source_row} 列）更新：" + "、".join(changes) + f"。其他欄位未變更；{reason}",
    )
    from sales.services.order_search import rebuild_order_search_index
    rebuild_order_search_index(order.pk)
    row.committed_model, row.committed_pk = "SalesOrder", str(order.pk)
