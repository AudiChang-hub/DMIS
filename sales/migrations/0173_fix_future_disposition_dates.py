"""修正 0172 補正時推到未來的去向日期（使用者要求核對正式站庫存時發現）。

Excel 沒填進貨日期的 36 列，進貨日被設為匯入當天（2026-10-10），以它推算「月／日」的年份時，
早於進貨日的日期被推到隔年（例如「10/5季志調」成為 2027-10-05）。去向日期不可能晚於今天：
往前推一年直到不晚於今天，並寫庫存異動紀錄。
"""
from django.db import migrations
from django.utils import timezone

ACTOR = "系統（1.62.1 去向日期修正）"
REASON = "Excel 沒填進貨日期，去向日期年份推到未來；改為不晚於今天的最近日期"


def fix(apps, schema_editor):
    Vehicle = apps.get_model("sales", "VehicleInventory")
    History = apps.get_model("sales", "VehicleInventoryHistory")
    today = timezone.localdate()
    for vehicle in Vehicle.objects.select_related("current_dealer").filter(disposition_on__gt=today).order_by("id"):
        before = vehicle.disposition_on
        after = before
        try:
            while after > today:
                after = after.replace(year=after.year - 1)
        except ValueError:  # 2/29
            continue
        vehicle.disposition_on = after
        vehicle.save(update_fields=["disposition_on", "updated_at"])
        History.objects.create(
            vehicle=vehicle, event_type="updated", actor_name=ACTOR, reason=REASON,
            changes={"去向日期": {"before": str(before), "after": str(after)}},
            status_snapshot=vehicle.status, location_store_snapshot_id=vehicle.location_store_id,
            location_label_snapshot=vehicle.current_dealer.name if vehicle.current_dealer_id else "本店",
            condition_note_snapshot=vehicle.condition_note, condition_resolution_snapshot=vehicle.condition_resolution,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0172_backfill_imported_inventory_location"),
    ]

    operations = [
        migrations.RunPython(fix, migrations.RunPython.noop),
    ]
