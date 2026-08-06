#!/usr/bin/env python3
"""
透過 Odoo XML-RPC 呼叫 Excel 匯入 Wizard 的 action_import，
執行完整匯入並顯示結果。
"""
import xmlrpc.client
import base64
import os
import sys

ODOO_URL = os.environ.get('ODOO_URL', 'http://localhost:8069')
DB = os.environ.get('ODOO_DB', 'dmis_dev')
USER = os.environ.get('ODOO_USERNAME', 'admin')
PASSWORD = os.environ.get('ODOO_PASSWORD')
EXCEL_PATH = os.environ.get('EXCEL_IMPORT_PATH', '/home/audi/project/DMIS/車輛進銷貨庫存表(客戶資料).xlsx')
if not PASSWORD:
    raise SystemExit('請先設定 ODOO_PASSWORD 環境變數。')

common = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/common')
uid = common.authenticate(DB, USER, PASSWORD, {})
models = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/object')

with open(EXCEL_PATH, 'rb') as f:
    file_data = base64.b64encode(f.read()).decode()

wiz_id = models.execute_kw(DB, uid, PASSWORD, 'dms.excel.import.wizard', 'create', [{
    'file_data': file_data,
    'file_name': '車輛進銷貨庫存表(客戶資料).xlsx',
}])
print(f"✓ Wizard id={wiz_id}，開始匯入...")

models.execute_kw(DB, uid, PASSWORD, 'dms.excel.import.wizard', 'action_import', [[wiz_id]])

result = models.execute_kw(DB, uid, PASSWORD, 'dms.excel.import.wizard', 'read',
    [[wiz_id]], {'fields': ['preview_insert', 'preview_update', 'preview_skip', 'error_summary']})

r = result[0]
print(f"\n=== 匯入結果 ===")
print(f"  ✅ 新增：{r['preview_insert']} 筆")
print(f"  🔄 更新：{r['preview_update']} 筆")
print(f"  ⚪ 略過：{r['preview_skip']} 筆")

if r['error_summary']:
    print(f"\n錯誤/警告：\n{r['error_summary']}")
else:
    print("\n✅ 全部成功，無任何錯誤")

# 確認實際筆數
count = models.execute_kw(DB, uid, PASSWORD, 'dms.sale.order', 'search_count',
    [[['excel_sync_id', '!=', False]]])
print(f"\nDB 中來自 Excel 的訂單總數：{count} 筆")
