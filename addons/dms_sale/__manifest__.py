{
    'name': 'DMS 銷售管理',
    'version': '16.0.1.0.0',
    'summary': '銷售訂單、精品明細',
    'author': 'DMIS',
    'license': 'LGPL-3',
    'category': 'Custom',
    'depends': ['dms_core', 'dms_product', 'dms_pricelist', 'dms_customer'],
    'data': [
        'security/ir.model.access.csv',
        'data/sequence.xml',
        'views/vehicle_color_views.xml',
        'views/sale_order_views.xml',
    ],
    'installable': True,
    'application': True,
}
