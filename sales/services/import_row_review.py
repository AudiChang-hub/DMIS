"""匯入修正的唯讀差異提示；不判定取消、不覆寫訂單、不自動略過。"""
import re

from django.db.models import Q

from sales.models import LegacyImportRow, SalesOrder, VehicleInventory, normalize_vehicle_identifier


COMPARISON_FIELDS = {
    "owner_name": "車主姓名",
    "registration_date": "實際領牌日期",
    "order_date": "訂單日期",
    "model_number": "車種型號",
    "plate_number": "車牌號碼",
    "color": "顏色",
    "dealer_name": "來源名稱",
}


def _text(value):
    return str(value if value is not None else "").strip()


def build_import_row_review(row, labels):
    notes = {}
    messages = [str(message) for message in row.messages]
    for key, label in labels.items():
        matched = [m for m in messages if re.search(rf"\b{re.escape(key)}\b", m) or label in m]
        if matched:
            notes[key] = f"請核對{label}：" + "；".join(matched)
    if any("allocated_vehicle" in m or "識別號碼" in m for m in messages):
        notes["identifier_raw"] = "請核對引擎／車身號碼；同車輛可能已有訂單，不代表號碼一定填錯。"
    comparisons = []
    peer_rows = []
    related_vehicles = []
    identifier = normalize_vehicle_identifier(row.mapped_data.get("identifier_raw") or row.mapped_data.get("identifier"))
    if row.sheet_name in {"銷貨", "進貨"} and identifier:
        related_vehicles = list(VehicleInventory.objects.filter(Q(normalized_engine_number=identifier)
            | Q(normalized_frame_number=identifier)).select_related("vehicle_model").order_by("pk"))
        # 號碼正規化後精確比對，不以姓名、日期或 Excel 列號猜測同一筆訂單。
        orders = SalesOrder.objects.filter(
            Q(allocated_vehicle__normalized_engine_number=identifier)
            | Q(allocated_vehicle__normalized_frame_number=identifier)
            | Q(legacy_snapshot__import_row__mapped_data__identifier=identifier),
        ).select_related("vehicle_model", "color", "source", "allocated_vehicle", "legacy_snapshot__import_row").distinct().order_by("pk")
        # 所有同號碼訂單都要可見；新車／中古／已取消是核對資訊，不是排除條件。
        for order in orders:
            snapshot = getattr(order, "legacy_snapshot", None)
            previous = snapshot.import_row.mapped_data if snapshot else None
            current = {
                "owner_name": order.owner_name,
                "registration_date": order.registration_date,
                "order_date": order.order_date,
                "model_number": order.vehicle_model.model_number if order.vehicle_model else "",
                "plate_number": order.final_plate_number,
                "color": order.color.name if order.color else "",
                "dealer_name": order.source.name if order.source else "",
            }
            differences = []
            values = []
            for key, label in COMPARISON_FIELDS.items():
                incoming = _text(row.mapped_data.get(key))
                old = _text(previous.get(key)) if previous is not None else None
                now = _text(current[key])
                changed = incoming != now or (old is not None and incoming != old)
                if changed:
                    differences.append(key)
                    notes[key] = "本次 Excel 與既有訂單或上次匯入內容不同，請先核對差異表，不會自動覆寫原訂單。"
                values.append({"key": key, "label": label, "previous": old, "current": now, "incoming": incoming, "changed": changed})
            incoming_id = _text(row.mapped_data.get("owner_id_number")).upper()
            existing_id = _text(order.owner_id_number).upper()
            identity_changed = bool(incoming_id and existing_id and not existing_id.startswith("HIST-") and incoming_id != existing_id)
            if identity_changed:
                notes["owner_id_number"] = "車主證號與既有訂單不同，請核對是否為不同買家；不會自動覆寫原訂單。"
            if row.sheet_name == "進貨":
                title = "同號碼已有銷售紀錄：請核對庫存與交易"
                guidance = "進貨與銷貨是不同用途的資料，買家欄位空白不代表退訂。請先核對車輛狀態與相關訂單。"
            elif row.mapped_data.get("vehicle_category") and row.mapped_data["vehicle_category"] != order.vehicle_category:
                title = "同車輛的不同交易類別：請核對完整歷史"
                guidance = "新車與中古轉售可能是合法的不同交易，不會僅憑相同號碼判定重複或取消原單。"
            elif "owner_name" in differences or identity_changed:
                title = "車主資料不同：請核對是否退訂後換買家"
                guidance = "Excel 換名字不代表原訂單已取消。請先查看原訂單的退訂、收退款及配車狀態，再決定如何處理；不可直接把原訂單改成新買家。"
            elif "registration_date" in differences:
                title = "領牌日期不同：請核對是否改期"
                guidance = "可能是同一張訂單改期，不應只因日期不同再建立一張。請至原訂單確認實際領牌日期，並由訂單流程處理相關異動。"
            elif differences:
                title = "同一車輛有資料差異，需人工核對"
                guidance = "請比對既有訂單及上次匯入內容，確認是資料更新或另一筆交易。"
            else:
                title = "主要欄位相同：疑似重複匯入"
                guidance = "仍須核對收支及其他欄位，不能僅憑車輛號碼自動略過；確認重複後可選擇不匯入此列並填寫原因。"
            vehicle = order.allocated_vehicle
            occupies = bool(vehicle and identifier in {vehicle.normalized_engine_number, vehicle.normalized_frame_number})
            comparisons.append({"order": order, "title": title, "guidance": guidance, "values": values,
                                "occupies_vehicle": occupies, "previous_row": snapshot.import_row if snapshot else None})
        peer_rows = list(LegacyImportRow.objects.filter(batch_id=row.batch_id, mapped_data__identifier=identifier)
                         .exclude(pk=row.pk).order_by("sheet_name", "source_row", "pk"))
        if comparisons:
            notes.setdefault("identifier_raw", "同一車輛已有訂單，請先核對差異與原訂單狀態，不要為了通過檢查而修改正確號碼。")
    from sales.services.legacy_import import friendly_import_message

    replacement_candidates = [item["order"] for item in comparisons
        if row.batch.status == "completed" and row.action == "error" and not row.committed_model and not row.committed_pk
        and row.sheet_name == "銷貨" and row.mapped_data.get("vehicle_category") == SalesOrder.VehicleCategory.NEW
        and item["occupies_vehicle"] and item["order"].vehicle_category == SalesOrder.VehicleCategory.NEW
        and _text(row.mapped_data.get("owner_name")) and _text(row.mapped_data.get("owner_name")) != item["order"].owner_name.strip()]
    return {"notes": notes, "comparisons": comparisons, "peer_rows": peer_rows, "identifier": identifier,
            "replacement_candidates": replacement_candidates,
            "related_vehicles": related_vehicles,
            "messages": [friendly_import_message(message) for message in messages]}
