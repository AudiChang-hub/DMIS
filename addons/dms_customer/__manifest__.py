{
    'name': 'DMS 客戶管理',
    'version': '16.0.1.1.0',
    'summary': '車行客戶資料管理（擴充聯絡人、舊車資訊）',
    'author': 'DMIS',
    'license': 'LGPL-3',
    'category': 'Custom',
    'depends': ['base', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'views/customer_views.xml',
    ],
    'installable': True,
    'application': True,
    'assets': {
        'web.assets_backend': [
            'dms_customer/static/src/js/dms_customer_column_limit.js',
        ],
    },
}
