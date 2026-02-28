{
    'name': 'DMS 產品管理',
    'version': '16.0.1.0.0',
    'summary': '車行產品（車款）管理',
    'author': 'DMIS',
    'license': 'LGPL-3',
    'category': 'Custom',
    'depends': ['dms_core', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'views/product_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'dms_product/static/src/js/dms_product_column_limit.js',
        ],
    },
    'installable': True,
    'application': True,
}
