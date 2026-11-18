"""T-238b 第一步（使用者 2026-11-18 同意刪除來源代碼）：來源代碼欄位先從程式狀態移除，資料庫欄位補預設值。

依「先擴充、後收斂」：2.27.0 起程式已不讀寫這兩個欄位，但部署切換的幾秒內舊版仍在跑；
這一步只移除 model 狀態，資料庫欄位保留並補 db_default=""，新版新增資料時不會因必填欄位失敗。
下一版（0220）才真正刪除資料庫欄位。
"""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales", "0218_order_bulk_update_access")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.AlterField(
                    model_name="salessource", name="code",
                    field=models.CharField("來源代碼", max_length=40, blank=True, default="", db_default=""),
                ),
                migrations.AlterField(
                    model_name="pricelistdistributionitem", name="dealer_code",
                    field=models.CharField("車行代碼快照", max_length=40, blank=True, default="", db_default=""),
                ),
            ],
            state_operations=[
                migrations.RemoveField(model_name="salessource", name="code"),
                migrations.RemoveField(model_name="pricelistdistributionitem", name="dealer_code"),
            ],
        ),
    ]
