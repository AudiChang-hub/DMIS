#!/usr/bin/env python3
"""
透過 XML-RPC 呼叫 dms.excel.import.wizard 執行 Excel 銷貨資料匯入
用法：
  python3 scripts/rpc_excel_import.py <excel_file_path>
"""
import base64
import os
import sys
import xmlrpc.client

PORT = os.environ.get('ODOO_PORT', '8069')
DB = os.environ.get('POSTGRES_DB', 'dmis_dev')
USER = os.environ.get('ODOO_ADMIN_USER', 'admin')
PASSWORD = os.environ.get('ODOO_ADMIN_PASSWORD')
HOST = os.environ.get('ODOO_HOST', 'localhost')

if not PASSWORD:
    raise SystemExit('請先設定 ODOO_ADMIN_PASSWORD 環境變數。')

if len(sys.argv) < 2:
    print("用法：python3 scripts/rpc_excel_import.py <excel_檔案路徑>")
    sys.exit(1)

excel_path = sys.argv[1]
if not os.path.exists(excel_path):
    print(f"錯誤：找不到檔案 {excel_path}")
    sys.exit(1)

# ── 1. 認證
common = xmlrpc.client.ServerProxy(f'http://{HOST}:{PORT}/xmlrpc/2/common')
uid = common.authenticate(DB, USER, PASSWORD, {})
if not uid:
    print(f"AUTH FAIL: 無法以 {USER} 登入 {DB}")
    sys.exit(2)
print(f"✅ 認證成功 uid={uid}")

models = xmlrpc.client.ServerProxy(f'http://{HOST}:{PORT}/xmlrpc/2/object')

# ── 2. 讀取並 base64 編碼 Excel
with open(excel_path, 'rb') as f:
    file_b64 = base64.b64encode(f.read()).decode('utf-8')
file_name = os.path.basename(excel_path)
print(f"📄 已讀取 {file_name}")

# ── 3. 建立 wizard 記錄
wizard_id = models.execute_kw(DB, uid, PASSWORD,
    'dms.excel.import.wizard', 'create',
    [{'file_data': file_b64, 'file_name': file_name}])
print(f"🧙 Wizard 建立成功 id={wizard_id}")

# ── 4. 預覽（取得筆數）
models.execute_kw(DB, uid, PASSWORD,
    'dms.excel.import.wizard', 'action_preview',
    [[wizard_id]])

wizard = models.execute_kw(DB, uid, PASSWORD,
    'dms.excel.import.wizard', 'read',
    [[wizard_id]],
    {'fields': ['preview_insert', 'preview_update', 'preview_skip', 'error_summary']})
w = wizard[0]
print(f"\n📊 預覽結果：")
print(f"   將新增：{w['preview_insert']} 筆")
print(f"   將更新：{w['preview_update']} 筆")
print(f"   略過（無序號）：{w['preview_skip']} 筆")
if w.get('error_summary'):
    print(f"\n⚠️  警告：\n{w['error_summary'][:500]}")

if w['preview_insert'] + w['preview_update'] == 0:
    print("\n⛔ 無資料可匯入，中止。")
    sys.exit(3)

# ── 5. 執行匯入
print(f"\n⏳ 開始匯入，請稍候...")
models.execute_kw(DB, uid, PASSWORD,
    'dms.excel.import.wizard', 'action_import',
    [[wizard_id]])

# ── 6. 讀取結果
wizard = models.execute_kw(DB, uid, PASSWORD,
    'dms.excel.import.wizard', 'read',
    [[wizard_id]],
    {'fields': ['preview_insert', 'preview_update', 'preview_skip', 'error_summary']})
w = wizard[0]
print(f"\n🎉 匯入完成：")
print(f"   新增：{w['preview_insert']} 筆")
print(f"   更新：{w['preview_update']} 筆")
print(f"   略過：{w['preview_skip']} 筆")
if w.get('error_summary'):
    print(f"\n詳細結果：\n{w['error_summary']}")
