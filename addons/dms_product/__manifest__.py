{
    'name': 'DMS 產品管理',
    'version': '16.0.2.1.0',
    'summary': '新一代產品模板、SKU、價目版本、分期規則與費用規則管理',
    'description': (
        '提供產品模板、可販售產品項 / SKU、價目版本、價格基準、'
        '分期規則模板、費用類型與規則掛接等主資料，'
        '並作為產品管理的唯一正式入口。'
    ),
    'author': 'DMIS',
    'license': 'LGPL-3',
    'category': 'Custom',
    'depends': ['dms_core', 'dms_sale'],
    'data': [
        'security/ir.model.access.csv',
        'data/fee_type_data.xml',
        'views/product_template_views.xml',
        'views/product_sku_views.xml',
        'views/price_version_views.xml',
        'views/price_version_bulk_add_wizard_views.xml',
        'views/price_line_views.xml',
        'views/installment_rule_views.xml',
        'views/fee_type_views.xml',
        'views/installment_rule_binding_views.xml',
        'views/menu_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'assets': {
        'web.assets_backend': [
            'dms_product/static/src/js/sku_o2m_autosave.js',
        ],
    },
    'installable': True,
    'application': True,
}
