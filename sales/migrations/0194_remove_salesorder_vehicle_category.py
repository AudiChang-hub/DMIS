"""車輛類別併入交易類型（使用者 2026-10-20）。

原本 model／表單強制「車輛類別＝中古車 ⇔ 交易類型＝中古車交易」，車輛類別可完全
由交易類型推導，所以直接移除欄位。反向會加回欄位並依交易類型回填，不會遺失資料。
"""

from django.db import migrations, models


def align_transaction_type(apps, schema_editor):
    # 保險：舊規則下不該出現，但若有車輛類別＝中古車而交易類型不是中古車交易，
    # 以車輛類別為準改成中古車交易，避免刪欄後失去中古車標記。
    SalesOrder = apps.get_model("sales", "SalesOrder")
    SalesOrder._base_manager.filter(vehicle_category="used").exclude(
        transaction_type="used"
    ).update(transaction_type="used")


def backfill_vehicle_category(apps, schema_editor):
    SalesOrder = apps.get_model("sales", "SalesOrder")
    SalesOrder._base_manager.filter(transaction_type="used").update(vehicle_category="used")


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0193_plate_insurance_auto"),
    ]

    operations = [
        migrations.RunPython(align_transaction_type, backfill_vehicle_category),
        migrations.RemoveField(
            model_name="salesorder",
            name="vehicle_category",
        ),
    ]
