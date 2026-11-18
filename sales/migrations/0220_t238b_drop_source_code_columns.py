"""T-238b 第二步（使用者 2026-11-18 同意刪除）：刪除來源代碼的資料庫欄位。

0219（上一版）已把兩個欄位從 model 移除並補 db_default；上一版程式完全不讀寫，舊版上線時先刪欄位也不會出錯。
回復時補回空白欄位（舊值不還原，部署前備份保有原資料）。
"""
from django.db import migrations


class Migration(migrations.Migration):
    # 已確認上一版（含 0219）程式與 model 都不再使用這兩個欄位。
    zero_downtime_safe = True

    dependencies = [("sales", "0219_t238b_remove_source_code_state")]

    operations = [
        migrations.RunSQL(
            sql='ALTER TABLE "sales_salessource" DROP COLUMN "code";',
            reverse_sql='ALTER TABLE "sales_salessource" ADD COLUMN "code" varchar(40) DEFAULT \'\' NOT NULL;',
        ),
        migrations.RunSQL(
            sql='ALTER TABLE "sales_pricelistdistributionitem" DROP COLUMN "dealer_code";',
            reverse_sql='ALTER TABLE "sales_pricelistdistributionitem" ADD COLUMN "dealer_code" varchar(40) DEFAULT \'\' NOT NULL;',
        ),
    ]
