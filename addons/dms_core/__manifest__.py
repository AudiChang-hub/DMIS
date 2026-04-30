{
    'name': 'DMS 車行管理',
    'version': '16.0.1.2.1',
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
        'views/web_layout_override.xml',
        'views/system_about_views.xml',
        'data/company_config.xml',
        'data/seed.xml',
    ],
    # 已移除自建前端資產（dealer_columns_button.js）

    'assets': {
        'web.assets_backend': [
            'dms_core/static/src/scss/dealer.scss',
            'dms_core/static/src/scss/dms_theme.scss',
            'dms_core/static/src/js/dms_dealer_column_limit.js',
            'dms_core/static/src/xml/color_dot_field.xml',
            'dms_core/static/src/js/color_dot_field.js',
            'dms_core/static/src/js/dms_webclient_patch.js',
        ],
    },

    'installable': True,
    'application': True,
}
