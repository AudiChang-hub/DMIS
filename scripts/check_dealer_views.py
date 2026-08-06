import os
import xmlrpc.client

url = os.environ.get('ODOO_URL', 'http://localhost:8069')
db = os.environ.get('ODOO_DB', 'dmis_dev')
username = os.environ.get('ODOO_USERNAME')
password = os.environ.get('ODOO_PASSWORD')
if not username or not password:
    raise SystemExit('請先設定 ODOO_USERNAME 與 ODOO_PASSWORD 環境變數。')
common=xmlrpc.client.ServerProxy('{}/xmlrpc/2/common'.format(url))
uid=common.login(db, username, password)
print('uid', uid)
models=xmlrpc.client.ServerProxy('{}/xmlrpc/2/object'.format(url))
views = models.execute_kw(db, uid, password, 'ir.ui.view', 'search_read', [[['model', '=', 'dms.dealer']]], {'fields': ['id','name','arch']})
print('Found %d views for dms.dealer' % len(views))
for v in views:
    print('--- id:', v['id'], 'name:', v['name'])
    arch = v.get('arch')
    if arch:
        snippet = arch[:400].replace('\n',' ')
        print('arch snippet:', snippet)
    else:
        print('no arch')
