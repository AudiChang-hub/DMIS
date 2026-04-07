{
    'name': 'DMS 零件管理（已合併至產品及零件管理）',
    'version': '16.0.1.1.0',
    'summary': '零件功能已移入 dms_product，此為向下相容空殼模組',
    'author': 'DMIS',
    'license': 'LGPL-3',
    'category': 'Custom',
    'depends': ['dms_product'],
    'data': [
        'views/cleanup.xml',
    ],
    'installable': True,
    'application': False,
}
