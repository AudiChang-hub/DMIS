import os
import xmlrpc.client
from lxml import etree

url = os.environ.get('ODOO_URL', 'http://localhost:8069')
db = os.environ.get('ODOO_DB', 'dmis_dev')
username = os.environ.get('ODOO_USERNAME')
password = os.environ.get('ODOO_PASSWORD')
if not username or not password:
    raise SystemExit('請先設定 ODOO_USERNAME 與 ODOO_PASSWORD 環境變數。')

# parse local xml
fn='addons/dms_core/views/dealer_views.xml'
with open(fn, 'r', encoding='utf-8') as f:
    doc = etree.parse(f)
root = doc.getroot()
records = []
for rec in root.findall('.//record'):
    model = rec.get('model')
    if model != 'ir.ui.view':
        continue
    name_field = rec.find("field[@name='name']")
    if name_field is None or not name_field.text:
        continue
    view_name = name_field.text.strip()
    arch_field = rec.find("field[@name='arch']")
    if arch_field is None:
        continue
    # get inner xml string of arch_field
    arch_children = ''.join([etree.tostring(c, encoding='unicode') for c in arch_field])
    records.append((view_name, arch_children))

common=xmlrpc.client.ServerProxy('{}/xmlrpc/2/common'.format(url))
uid=common.login(db, username, password)
models=xmlrpc.client.ServerProxy('{}/xmlrpc/2/object'.format(url))
print('uid', uid)
for name, arch in records:
    print('Updating view', name)
    vid = models.execute_kw(db, uid, password, 'ir.ui.view', 'search', [[['name','=',name]]], {'limit':1})
    if not vid:
        print(' no view found for', name)
        continue
    try:
        res = models.execute_kw(db, uid, password, 'ir.ui.view', 'write', [vid, {'arch_db': arch}])
        print(' write result', res)
    except Exception as e:
        print(' error writing', e)
