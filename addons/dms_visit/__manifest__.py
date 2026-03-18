{
    'name': 'DMS 拜訪紀錄',
    'version': '16.0.1.0.0',
    'summary': '車行拜訪紀錄管理（清單＋行事曆）',
    'description': (
        '管理拜訪車行的紀錄，包含拜訪目的、拜訪人員、送出物品明細等，'
        '整合至現有車行管理模組，提供清單與行事曆兩種界面。'
    ),
    'author': 'DMIS',
    'license': 'LGPL-3',
    'category': 'Custom',
    'depends': ['dms_core', 'dms_product'],
    'data': [
        'security/dms_visit_security.xml',
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'views/visit_purpose_views.xml',
        'views/visit_views.xml',
        'views/dealer_visit_inherit.xml',
    ],
    'installable': True,
    'application': False,
}
