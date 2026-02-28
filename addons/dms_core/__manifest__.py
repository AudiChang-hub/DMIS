{
    'name': 'DMS Core',
    'version': '16.0.1.0.0',
    'summary': '最小車行管理示範',
    'description': '提供 dealer（車行）模型與基本 view，作為專案骨架示範。',
    'author': 'DMIS',
    'license': 'LGPL-3',
    'category': 'Custom',
    'depends': ['base', 'web'],
    'data': [
        'security/dms_security.xml',
        'security/ir.model.access.csv',
        'views/dealer_views.xml',
        'views/brand_views.xml',
        'views/store_type_views.xml',
        'views/product_views.xml',
        'data/seed.xml',
    ],
    # 已移除自建前端資產（dealer_columns_button.js）

    'assets': {
        'web.assets_backend': [
            'dms_core/static/src/scss/dealer.scss',
            'dms_core/static/src/js/dms_dealer_column_limit.js',
        ],
    },

    'installable': True,
    'application': True,
}
