from django.db import migrations

# 使用者 2026-11-12 T-153：配件類別「乘載」改名為「其他」（需求簡報第 2 頁「不用『乘載』這個類別，改成『其他』」）。
# 正式資料寫入，使用者同意本次一次性執行；部署腳本會先備份資料庫。
# - 只有「乘載」：原地改名，掛在底下的配件主檔外鍵不變，一併歸到「其他」。
# - 已經有「其他」：把「乘載」底下的配件搬到「其他」，「乘載」停用（不刪，避免遺失紀錄）。
# 訂單配件明細（AccessoryLine）不存類別，不受影響。
OLD_NAME = "乘載"
NEW_NAME = "其他"


def rename_to_other(apps, schema_editor):
    Category = apps.get_model("sales", "AccessoryCategory")
    old = Category.objects.filter(name=OLD_NAME).first()
    if old is None:
        return
    target = Category.objects.filter(name=NEW_NAME).first()
    if target is None:
        old.name = NEW_NAME
        old.save(update_fields=["name", "updated_at"])
        return
    old.products.update(category=target)
    old.active = False
    old.save(update_fields=["active", "updated_at"])


def rename_back(apps, schema_editor):
    # 只回復「原地改名」的情況；合併的情況無法分辨哪些配件原本屬於「乘載」，維持現狀。
    Category = apps.get_model("sales", "AccessoryCategory")
    if Category.objects.filter(name=OLD_NAME).exists():
        return
    Category.objects.filter(name=NEW_NAME).update(name=OLD_NAME)


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0204_dealer_payouts"),
    ]

    operations = [
        migrations.RunPython(rename_to_other, rename_back),
    ]
