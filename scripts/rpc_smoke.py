#!/usr/bin/env python3
import os
import sys
import xmlrpc.client

PORT = os.environ.get('ODOO_PORT', '8069')
DB = os.environ.get('POSTGRES_DB', 'postgres')
USER = os.environ.get('ODOO_ADMIN_USER', 'admin')
PASSWORD = os.environ.get('ODOO_ADMIN_PASSWORD')
HOST = os.environ.get('ODOO_HOST', 'localhost')

if not PASSWORD:
    raise SystemExit('請先設定 ODOO_ADMIN_PASSWORD 環境變數。')

common_url = f'http://{HOST}:{PORT}/xmlrpc/2/common'
object_url = f'http://{HOST}:{PORT}/xmlrpc/2/object'

print('Connecting to', common_url)
common = xmlrpc.client.ServerProxy(common_url)
uid = common.authenticate(DB, USER, PASSWORD, {})
if not uid:
    print('AUTH FAIL: Could not authenticate as', USER)
    sys.exit(2)
print('Authenticated uid=', uid)

models = xmlrpc.client.ServerProxy(object_url)
try:
    # Check seed records exist
    codes = ['D001', 'D002', 'D003']
    count = models.execute_kw(DB, uid, PASSWORD, 'dms.dealer', 'search_count', [[('code', 'in', codes)]])
    print('Found dealers with codes', codes, ':', count)
    if count < 3:
        print('SEED FAIL: expected at least 3 seeded dealers')
        sys.exit(3)

    # Check name_search works for code
    res = models.execute_kw(DB, uid, PASSWORD, 'dms.dealer', 'name_search', ['D001'], {'operator': 'ilike', 'limit': 5})
    print('name_search("D001") ->', res)
    if not res:
        print('NAME_SEARCH FAIL')
        sys.exit(4)

    print('RPC smoke OK')
    sys.exit(0)
except xmlrpc.client.Fault as e:
    print('XML-RPC Fault:', e)
    # Try to report module installation state
    try:
        mod = models.execute_kw(DB, uid, PASSWORD, 'ir.module.module', 'search_read', [[('name', '=', 'dms_core')]], {'fields': ['state'], 'limit': 1})
        print('dms_core module state:', mod)
    except Exception as e2:
        print('Could not read module state:', e2)
    sys.exit(5)
