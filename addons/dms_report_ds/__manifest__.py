{
    'name': 'DMS DataStudio 銷售分析',
    'version': '16.0.1.0.0',
    'category': 'Sales/Reporting',
    'summary': '復刻 DataStudio 銷售統計報表（SQL View + Odoo 視圖）',
    'description': """
        基於 dms.sale.order 建立 SQL View (ds_sales_report)，
        包含 17 個 DataStudio 計算欄位，提供 Pivot / Graph / Tree 視圖。
        搭配 Metabase 可完整復刻 22 頁 Dashboard。
    """,
    'author': '馭盛車業',
    'depends': ['dms_sale', 'dms_commission'],
    'data': [
        'security/ir.model.access.csv',
        'views/ds_report_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
