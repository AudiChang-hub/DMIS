import xmlrpc.client

url='http://localhost:8069'
db='dmis_dev'
username='hongsian.c@gmail.com'
password='@Sa095328odoo'

common=xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
uid=common.login(db, username, password)
print('uid', uid)
models=xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

for view_type in ('form','tree'):
    try:
        print('\n--- fields_view_get', view_type)
        res = models.execute_kw(db, uid, password, 'dms.dealer', 'fields_view_get', [False, view_type])
        arch = res.get('arch', '')
        print('arch length', len(arch))
        # parse simple xml for field names
        try:
            from xml.etree import ElementTree as ET
            root = ET.fromstring(arch)
            names = [n.get('name') for n in root.findall('.//field') if n.get('name')]
            print('fields in view:', names)
        except Exception as e:
            print('parse arch error', e)
    except Exception as e:
        print('ERROR calling fields_view_get', e)
        print('Attempting to locate view record directly and read arch...')
        try:
            vids = models.execute_kw(db, uid, password, 'ir.ui.view', 'search', [[['model','=', 'dms.dealer'], ['type','=', view_type]]])
            print('found view ids', vids)
            if vids:
                recs = models.execute_kw(db, uid, password, 'ir.ui.view', 'read', [vids], {'fields':['id','name','arch']})
                for r in recs:
                    print('view', r.get('id'), r.get('name'), 'arch_len', len(r.get('arch') or ''))
            else:
                print('no view records found for type', view_type)
        except Exception as e2:
            print('ERROR reading ir.ui.view', e2)
