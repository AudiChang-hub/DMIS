import xmlrpc.client
url='http://localhost:8069'
db='dmis_dev'
username='hongsian.c@gmail.com'
password='@Sa095328odoo'
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
