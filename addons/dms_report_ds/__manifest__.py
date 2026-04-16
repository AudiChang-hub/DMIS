{
    'name': 'DMS DataStudio 銷售分析',
    'version': '16.0.1.1.0',
    'category': 'Sales/Reporting',
    'summary': '復刻 DataStudio 銷售統計報表（SQL View + Odoo 視圖）',
    'description': """
        基於 dms.sale.order 建立 SQL View (ds_sales_report)，
        包含 17 個 DataStudio 計算欄位，提供 Pivot / Graph / Tree 視圖。
        搭配 Metabase 可完整復刻 22 頁 Dashboard。
        整併報表分析選單至銷售分析。
    """,
    'author': '馭盛車業',
    'depends': [
        'dms_sale',
        'dms_commission',
        'dms_report',
        'dms_report_rule',
        'dms_report_virtual',
        'spreadsheet_dashboard',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/metabase_config.xml',
        'views/ds_report_views.xml',
        'views/metabase_actions.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'dms_report_ds/static/src/js/metabase_dashboard.js',
            'dms_report_ds/static/src/xml/metabase_dashboard.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
