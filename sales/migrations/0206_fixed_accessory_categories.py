from django.db import migrations

# 使用者 2026-11-13 T-153：配件類別固定為 7 類（需求簡報第 2 頁），正式資料寫入，使用者同意本次一次性執行；
# 部署腳本會先備份資料庫。訂單配件明細（AccessoryLine）不存類別，不受影響。
# - 保留：安全帽、手機架、保桿。
# - 改名：電子與鑰匙→行車紀錄器、外觀改裝→改裝部品、乘載→其他（原地改名，底下的配件跟著走）。
# - 刪除：後貨架／置物等不在名單上的類別（底下配件依外鍵 SET_NULL 暫時變成未分類，部署後由
#   assign_accessory_categories 指令依使用者逐筆指定的類別歸類）。
# - 新增：原廠配件。
# 改名目標已存在時，把舊類別的配件搬過去再刪掉舊類別。
FINAL = [
    ("安全帽", 10),
    ("手機架", 20),
    ("行車紀錄器", 30),
    ("保桿", 40),
    ("改裝部品", 50),
    ("原廠配件", 60),
    ("其他", 70),
]
RENAMES = [("電子與鑰匙", "行車紀錄器"), ("外觀改裝", "改裝部品"), ("乘載", "其他")]


def fix_categories(apps, schema_editor):
    Category = apps.get_model("sales", "AccessoryCategory")
    Product = apps.get_model("sales", "AccessoryProduct")
    for old_name, new_name in RENAMES:
        old = Category.objects.filter(name=old_name).first()
        if old is None:
            continue
        target = Category.objects.filter(name=new_name).first()
        if target is None:
            old.name = new_name
            old.save(update_fields=["name", "updated_at"])
        else:
            Product.objects.filter(category=old).update(category=target)
            old.delete()
    keep = [name for name, _order in FINAL]
    Category.objects.exclude(name__in=keep).delete()
    for name, order in FINAL:
        category, _created = Category.objects.get_or_create(name=name, defaults={"sort_order": order})
        if (category.sort_order, category.active) != (order, True):
            category.sort_order = order
            category.active = True
            category.save(update_fields=["sort_order", "active", "updated_at"])


def restore_categories(apps, schema_editor):
    # 回到 0199 的類別名稱與排序；刪掉的「後貨架／置物」重建為空類別（配件歸屬無法還原，需要時用部署前備份）。
    Category = apps.get_model("sales", "AccessoryCategory")
    for old_name, new_name in RENAMES:
        if not Category.objects.filter(name=old_name).exists():
            Category.objects.filter(name=new_name).update(name=old_name)
    Category.objects.filter(name="原廠配件", products__isnull=True).delete()
    original = ["安全帽", "手機架", "後貨架／置物", "保桿", "外觀改裝", "電子與鑰匙", "乘載"]
    for index, name in enumerate(original, start=1):
        category, _created = Category.objects.get_or_create(name=name, defaults={"sort_order": index * 10})
        Category.objects.filter(pk=category.pk).update(sort_order=index * 10)


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0205_owner_id_number_optional"),
    ]

    operations = [
        migrations.RunPython(fix_categories, restore_categories),
    ]
