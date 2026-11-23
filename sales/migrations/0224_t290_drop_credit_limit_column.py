"""T-290（T-288 第二步，使用者 2026-11-23 選 A「連欄位一起拿掉」）：刪除車行額度（credit_limit）的資料庫欄位。

0223（2.35.7）已把欄位從 model 狀態移除，上一版程式完全不讀寫，舊版上線時先刪欄位也不會出錯。
回復時補回可空欄位（原為 DecimalField max_digits=12 decimal_places=0 null=True；舊值不還原，部署前備份保有原資料）。
"""
from django.db import migrations


class Migration(migrations.Migration):
    # 已確認上一版（含 0223）程式與 model 都不再使用這個欄位。
    zero_downtime_safe = True

    dependencies = [("sales", "0223_t288_remove_credit_limit_state")]

    operations = [
        migrations.RunSQL(
            sql='ALTER TABLE "sales_salessource" DROP COLUMN "credit_limit";',
            reverse_sql='ALTER TABLE "sales_salessource" ADD COLUMN "credit_limit" numeric(12, 0) NULL;',
        ),
    ]
