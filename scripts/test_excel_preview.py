#!/usr/bin/env python3
"""
透過 Odoo XML-RPC 呼叫 Excel 匯入 Wizard 的 action_preview，
確認解析有無錯誤，不會寫入任何 dms.sale.order 資料。
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

# ── 登入
common = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/common')
uid = common.authenticate(DB, USER, PASSWORD, {})
if not uid:
    print("❌ 登入失敗，請確認帳號密碼")
    sys.exit(1)
print(f"✓ 登入成功 uid={uid}")

models = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/object')

# ── 讀取 Excel
with open(EXCEL_PATH, 'rb') as f:
    file_data = base64.b64encode(f.read()).decode()

# ── 建立 Wizard 記錄
wiz_id = models.execute_kw(DB, uid, PASSWORD, 'dms.excel.import.wizard', 'create', [{
    'file_data': file_data,
    'file_name': '車輛進銷貨庫存表(客戶資料).xlsx',
}])
print(f"✓ Wizard 建立成功 id={wiz_id}")

# ── 呼叫 action_preview
print("▶ 執行比對...")
models.execute_kw(DB, uid, PASSWORD, 'dms.excel.import.wizard', 'action_preview', [[wiz_id]])

# ── 讀取結果
result = models.execute_kw(DB, uid, PASSWORD, 'dms.excel.import.wizard', 'read',
    [[wiz_id]], {'fields': ['preview_insert', 'preview_update', 'preview_skip', 'error_summary']})

r = result[0]
print(f"\n=== 比對結果 ===")
print(f"  🟢 將新增：{r['preview_insert']} 筆")
print(f"  🟡 將更新：{r['preview_update']} 筆")
print(f"  ⚪ 略過（無序號）：{r['preview_skip']} 筆")

if r['error_summary']:
    print(f"\n⚠️  警告：\n{r['error_summary']}")
else:
    print("\n✅ 無警告")
