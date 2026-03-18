{
    'name': 'DMS 拜訪紀錄',
    'version': '16.0.1.1.0',
    'summary': '車行拜訪紀錄管理（清單＋行事曆＋Kanban）',
    'description': (
        '管理拜訪車行的紀錄，包含拜訪目的、拜訪人員、送出物品明細等，'
        '整合至現有車行管理模組，提供清單、行事曆與 Kanban 卡片三種界面。'
        '支援月度排程自動建立價格表拜訪紀錄。'
    ),
    'author': 'DMIS',
    'license': 'LGPL-3',
    'category': 'Custom',
    'depends': ['dms_core', 'dms_product'],
    'data': [
        'security/dms_visit_security.xml',
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'data/visit_cron.xml',
        'views/visit_purpose_views.xml',
        'views/visit_views.xml',
        'views/dealer_visit_inherit.xml',
        'views/dealer_kanban_inherit.xml',
        'views/kanban_config_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'dms_visit/static/src/css/pwa_pull_refresh.css',
            'dms_visit/static/src/js/pwa_pull_refresh.js',
        ],
    },
    'installable': True,
    'application': False,
}
