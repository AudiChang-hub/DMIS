{
    'name': '財務結算',
    'version': '16.0.1.0.0',
    'summary': '銷售財務結算、收入/支出明細、淨利計算',
    'description': '每筆銷售訂單的財務結算記錄，整合收入/支出明細並自動計算淨利，作為後續 BI 報表基礎。',
    'author': 'DMIS',
    'license': 'LGPL-3',
    'category': 'Custom',
    'depends': ['dms_sale'],
    'data': [
        'security/ir.model.access.csv',
        'views/sale_finance_views.xml',
        'views/sale_order_inherit_views.xml',
    ],
    'installable': True,
    'application': True,
}
