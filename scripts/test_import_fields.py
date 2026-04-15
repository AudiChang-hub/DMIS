#!/usr/bin/env python3
"""
乾跑測試：解析 Excel 並逐列執行 _build_vals，不寫入 DB
只驗證欄位對應是否正確
"""
import sys
import os
import subprocess

# 取得所有 sale_order 欄位
result = subprocess.run(
    ['docker', 'compose', 'exec', 'db', 'psql', '-U', 'odoo', '-d', 'dmis_dev',
     '-t', '-c', r'\d dms_sale_order'],
    capture_output=True, text=True, cwd='/home/audi/project/DMIS'
)
db_columns = set()
for line in result.stdout.splitlines():
    parts = line.strip().split()
    if parts:
        db_columns.add(parts[0])

print(f"DB 欄位數: {len(db_columns)}")

# 讀取 wizard 欄位
import re
wizard_path = '/home/audi/project/DMIS/addons/dms_sale/wizard/excel_import_wizard.py'
with open(wizard_path) as f:
    content = f.read()

# 擷取 vals['xxx'] = 的所有 key
wizard_fields = set(re.findall(r"vals\['([^']+)'\]\s*=", content))
print(f"Wizard 設定欄位數: {len(wizard_fields)}")

print("\n=== Wizard 設定但 DB 沒有的欄位 ===")
missing = wizard_fields - db_columns
for f in sorted(missing):
    print(f"  ❌ {f}")

print("\n=== 已確認存在的重要欄位 ===")
important = ['excel_sync_id', 'source_dealer_name', 'source_product_name',
             'subsidy_boie_status', 'subsidy_moenv_status', 'subsidy_city_status',
             'received_amount', 'amount_total', 'is_trade_in', 'note', 'state']
for f in important:
    status = "✓" if f in db_columns else "❌ 缺少"
    print(f"  {status} {f}")
