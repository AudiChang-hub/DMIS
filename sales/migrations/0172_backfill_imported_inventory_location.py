"""補正 1.61.0 前已匯入的 Excel 進貨資料（使用者 2026-10-10 要求並核准）。

舊版匯入把數量 0 設為停用、沒有讀 M～P 欄（存放／調車），實際位置全在本店。
依匯入列保存的原始資料（raw_data 的 M～P 欄）與數量重新判讀，只補仍是匯入預設值的欄位：
- 數量 0 且仍為停用 → 已售出；寫調出 → 已調出；車行領車 → 已售出並記去向。
- 數量 1 且仍在本店 → 依車行名稱改實際位置。
- 去向與備註只在空白時寫入；人工改過的車（狀態、位置、備註）維持不變。每台有異動都寫庫存異動紀錄。
"""
import re
import unicodedata

from django.db import migrations

from sales.services.inventory_location_note import resolve

COLUMNS = ("M", "N", "O", "P")
ACTOR = "系統（1.62.0 進貨資料補正）"
REASON = "依 Excel 進貨數量與存放／調車欄（M～P）重新判讀匯入資料"


def _normalize(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")).casefold())


def backfill(apps, schema_editor):
    Row = apps.get_model("sales", "LegacyImportRow")
    Vehicle = apps.get_model("sales", "VehicleInventory")
    History = apps.get_model("sales", "VehicleInventoryHistory")
    Source = apps.get_model("sales", "SalesSource")
    Mapping = apps.get_model("sales", "LegacyImportMasterMapping")

    mappings = {
        mapping.normalized_source_value: mapping
        for mapping in Mapping.objects.filter(mapping_type="sales_source").select_related("sales_source")
    }
    sources = {}
    for source in Source.objects.order_by("id"):
        sources.setdefault(source.name.casefold(), source)

    def find_dealer(name):
        mapping = mappings.get(_normalize(name))
        source = (None if mapping.ignored else mapping.sales_source) if mapping else sources.get(str(name).casefold())
        return source if source and source.source_type == "dealer" else None

    rows = Row.objects.filter(sheet_name="進貨", committed_model="VehicleInventory").order_by("id")
    for row in rows.iterator():
        if not str(row.committed_pk or "").isdigit():
            continue
        vehicle = Vehicle.objects.select_related("current_dealer").filter(pk=int(row.committed_pk)).first()
        if not vehicle:
            continue
        quantity = (row.mapped_data or {}).get("quantity")
        texts = [(row.raw_data or {}).get(column) for column in COLUMNS]
        in_stock = quantity == 1
        result = resolve(texts, vehicle.received_on, in_stock, find_dealer)
        before_status, before_location = vehicle.status, vehicle.current_dealer
        changed = []
        if quantity == 0 and vehicle.status == "inactive":
            vehicle.status = result["status"] or "sold"
            changed.append("status")
        if not vehicle.disposition and result["disposition"] and vehicle.status in ("sold", "transferred_out"):
            for field in ("disposition", "disposition_dealer", "disposition_dealer_name", "disposition_on"):
                setattr(vehicle, field, result[field])
            changed += ["disposition", "disposition_dealer", "disposition_dealer_name", "disposition_on"]
        if (in_stock and result["current_dealer"] and vehicle.current_dealer_id is None
                and vehicle.status in ("available", "condition_issue")):
            vehicle.current_dealer = result["current_dealer"]
            changed.append("current_dealer")
        if not vehicle.note and result["note"]:
            vehicle.note = result["note"]
            changed.append("note")
        if not changed:
            continue
        vehicle.save(update_fields=[*changed, "updated_at"])
        changes = {}
        if "status" in changed:
            changes["庫存狀態"] = {"before": before_status, "after": vehicle.status}
        if "current_dealer" in changed:
            changes["實際位置"] = {"before": "本店", "after": vehicle.current_dealer.name}
        if "disposition" in changed:
            changes["去向"] = {"before": "未記錄", "after": " ".join(
                part for part in (vehicle.disposition, vehicle.disposition_dealer_name, str(vehicle.disposition_on or "")) if part
            )}
        if "note" in changed:
            changes["備註"] = {"before": "未填寫", "after": vehicle.note}
        History.objects.create(
            vehicle=vehicle, event_type="updated", actor_name=ACTOR, reason=REASON, changes=changes,
            status_snapshot=vehicle.status, location_store_snapshot_id=vehicle.location_store_id,
            location_label_snapshot=vehicle.current_dealer.name if vehicle.current_dealer_id else "本店",
            condition_note_snapshot=vehicle.condition_note, condition_resolution_snapshot=vehicle.condition_resolution,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0171_vehicle_transfer_signoff"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
