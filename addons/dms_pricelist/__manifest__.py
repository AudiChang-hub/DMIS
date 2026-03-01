{
    'name': 'DMS 價目管理',
    'version': '16.0.1.0.0',
    'summary': '車款售價、精品售價、牌險費率、傭金規則',
    'author': 'DMIS',
    'license': 'LGPL-3',
    'category': 'Custom',
    'depends': ['dms_core', 'dms_product'],
    'data': [
        'security/ir.model.access.csv',
        'views/vehicle_price_views.xml',
        'views/accessory_views.xml',
        'views/accessory_price_views.xml',
        'views/fee_schedule_views.xml',
        'views/commission_rule_views.xml',
    ],
    'installable': True,
    'application': True,
}
