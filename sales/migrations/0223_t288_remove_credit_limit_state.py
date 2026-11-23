"""T-288 第一步（使用者 2026-11-23 選 A「連欄位一起拿掉」）：車行額度（credit_limit）先從程式狀態移除，資料庫欄位保留。

依「先擴充、後收斂」：這一版程式已不讀寫額度，但部署切換的幾秒內舊版仍在跑；欄位本來就可空，
不用補 db_default，資料庫完全不動。下一版（0224）才真正刪除資料庫欄位。

同版把交付紀錄 on_account_amount 的顯示名稱改成「交車時車行未付金額」（使用者 2026-11-23「全部一起改」），
只是 verbose_name，資料庫不動。
"""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales", "0222_t268_model_color_age_report")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveField(model_name="salessource", name="credit_limit"),
            ],
        ),
        migrations.AlterField(
            model_name="deliveryrecord",
            name="on_account_amount",
            field=models.DecimalField(
                decimal_places=0, default=0, editable=False, max_digits=12, verbose_name="交車時車行未付金額",
            ),
        ),
    ]
