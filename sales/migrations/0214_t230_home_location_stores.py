"""T-230 B（使用者 2026-11-18 選定）：庫存實際存放門市改成本店名稱。

- 總店（代碼 HQ）改名為「馭盛」；新增門市「永湛」。之後庫存「實際位置」最上面固定這兩間本店。
- 只在已有總店資料的環境執行（正式站）；空資料庫（測試、新環境）不建立任何門市。
- 只改名稱、新增一列，不動欄位，舊版程式照常運作；回復時改回「總店」，沒有車輛使用的永湛才刪除。
"""
from django.db import migrations

OLD_NAME = "總店"
MAIN_NAME = "馭盛"
SECOND_NAME = "永湛"
SECOND_CODE = "YZ"


def forwards(apps, schema_editor):
    Store = apps.get_model("sales", "Store")
    hq = Store.objects.filter(code__iexact="HQ").first()
    if hq is None:
        return
    if hq.name == OLD_NAME and not Store.objects.filter(name=MAIN_NAME).exists():
        hq.name = MAIN_NAME
        hq.save(update_fields=["name"])
    if not Store.objects.filter(name=SECOND_NAME).exists():
        code = SECOND_CODE
        suffix = 2
        while Store.objects.filter(code__iexact=code).exists():
            code = f"{SECOND_CODE}{suffix}"
            suffix += 1
        Store.objects.create(name=SECOND_NAME, code=code, active=True)


def backwards(apps, schema_editor):
    Store = apps.get_model("sales", "Store")
    VehicleInventory = apps.get_model("sales", "VehicleInventory")
    second = Store.objects.filter(name=SECOND_NAME).first()
    if second and not VehicleInventory.objects.filter(location_store=second).exists() \
            and not VehicleInventory.objects.filter(ownership_store=second).exists():
        second.delete()
    hq = Store.objects.filter(code__iexact="HQ", name=MAIN_NAME).first()
    if hq and not Store.objects.filter(name=OLD_NAME).exists():
        hq.name = OLD_NAME
        hq.save(update_fields=["name"])


class Migration(migrations.Migration):
    dependencies = [("sales", "0213_vehicle_color_code")]

    operations = [migrations.RunPython(forwards, backwards)]
