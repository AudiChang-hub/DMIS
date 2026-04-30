{
    'name': 'DMS 產品及零件管理',
    'version': '16.0.2.4.0',
    'summary': '產品模板、SKU、價目版本、分期規則、費用規則與零件清單管理',
    'description': (
        '提供產品模板、可販售產品項 / SKU、價目版本、價格基準、'
        '分期規則模板、費用類型與規則掛接等主資料，'
        '以及零件分類與零件清單（供傭金折換實物使用），'
        '並作為產品及零件管理的唯一正式入口。'
    ),
    'author': 'DMIS',
    'license': 'LGPL-3',
    'category': 'Custom',
    'depends': ['dms_core', 'dms_sale', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'data/fee_type_data.xml',
        'views/product_create_wizard_views.xml',
        'views/product_template_views.xml',
        'views/product_sku_views.xml',
        'views/price_version_views.xml',
        'views/price_version_bulk_add_wizard_views.xml',
        'views/price_line_views.xml',
        'views/installment_rule_views.xml',
        'views/fee_type_views.xml',
        'views/installment_rule_binding_views.xml',
        'views/product_duplicate_wizard_views.xml',
        'views/part_category_views.xml',
        'views/part_views.xml',
        'views/menu_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'assets': {
        'web.assets_backend': [
            'dms_product/static/src/js/sku_o2m_autosave.js',
            'dms_product/static/src/js/float_blank_zero.js',
            'dms_product/static/src/js/color_tags_widget.js',
            'dms_product/static/src/css/color_tags_widget.css',
            'dms_product/static/src/css/pricelist_sticky.css',
            'dms_product/static/src/js/pricelist_sticky.js',
            'dms_product/static/src/js/pricelist_create_button.js',
        ],
    },
    'installable': True,
    'application': True,
}
