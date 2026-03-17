{
    'name': '報表分析',
    'version': '16.0.1.0.0',
    'summary': '銷售、利潤、精品、傭金 BI 報表',
    'description': '以 Pivot / Graph 視圖彙整 dms_sale 與 dms_finance 的銷售與利潤資料，提供多維度分析。',
    'author': 'DMIS',
    'license': 'LGPL-3',
    'category': 'Custom',
    'depends': ['dms_sale', 'dms_finance'],
    'data': [
        'views/report_views.xml',
    ],
    'installable': True,
    'application': True,
}
