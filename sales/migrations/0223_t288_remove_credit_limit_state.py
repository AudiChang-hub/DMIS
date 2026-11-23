"""T-288 第一步（使用者 2026-11-23 選 A「連欄位一起拿掉」）：車行額度（credit_limit）先從程式狀態移除，資料庫欄位保留。

依「先擴充、後收斂」：這一版程式已不讀寫額度，但部署切換的幾秒內舊版仍在跑；欄位本來就可空，
不用補 db_default，資料庫完全不動。下一版（0224）才真正刪除資料庫欄位。
"""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("sales", "0222_t268_model_color_age_report")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveField(model_name="salessource", name="credit_limit"),
            ],
        ),
    ]
