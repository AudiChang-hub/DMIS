import xmlrpc.client,sys
url='http://localhost:8069'
db='dmis_dev'
username='hongsian.c@gmail.com'
password='@Sa095328odoo'
try:
    common=xmlrpc.client.ServerProxy('{}/xmlrpc/2/common'.format(url))
    uid=common.login(db, username, password)
    print('uid',uid)
    models=xmlrpc.client.ServerProxy('{}/xmlrpc/2/object'.format(url))
    test_sets = [
        ['code','name','phone_1'],
        ['code','phone_1'],
        ['name'],
    ]
    for idx, fields in enumerate(test_sets, start=1):
        print('\n--- Test', idx, 'fields=', fields)
        imf_ids=models.execute_kw(db, uid, password, 'ir.model.fields', 'search', [[['model','=','dms.dealer'], ['name','in', fields]]])
        print('ir.model.fields ids', imf_ids)
        if not imf_ids:
            print('no fields found, skipping')
            continue
        wiz_id=models.execute_kw(db, uid, password, 'dms.dealer.columns.wizard', 'create', [{'field_ids': [(6,0, imf_ids)]}])
        print('wizard id', wiz_id)
        res=models.execute_kw(db, uid, password, 'dms.dealer.columns.wizard', 'apply', [[wiz_id]])
        print('apply returned', res)
        user= models.execute_kw(db, uid, password, 'res.users', 'read', [uid], {'fields':['dms_dealer_tree_cols']})
        print('user cols', user)
        try:
            arch=models.execute_kw(db, uid, password, 'dms.dealer', 'fields_view_get', [False, 'tree'])['arch']
            print('arch:', arch)
            # try to parse arch to list field names
            try:
                from lxml import etree
                root = etree.fromstring(arch)
                names = [n.get('name') for n in root.findall('.//field') if n.get('name')]
                print('parsed field names:', names)
            except Exception as e:
                print('parse error', e)
        except Exception as e:
            print('ERROR', e)
            raise
except Exception as e:
    print('ERROR', e)
    raise
