{
    'name': 'DMS 零件管理',
    'version': '16.0.1.0.0',
    'summary': '零件清單管理，供傭金折換實物及未來維修保養使用',
    'author': 'DMIS',
    'license': 'LGPL-3',
    'category': 'Custom',
    'depends': ['dms_core'],
    'data': [
        'security/ir.model.access.csv',
        'views/part_category_views.xml',
        'views/part_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
}
