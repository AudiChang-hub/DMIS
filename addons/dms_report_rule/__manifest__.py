{
    'name': '報表規則設定',
    'version': '16.0.1.0.0',
    'summary': '動態報表規則：自訂維度、指標、圖表類型，一鍵預覽 Pivot / Graph',
    'description': (
        '讓管理者與分析人員不須修改程式碼，即可在系統介面定義報表規則，'
        '選擇資料模型、分析維度、指標欄位、圖表類型及篩選條件，'
        '並以 Odoo 原生 Pivot / Graph 視圖即時預覽。'
    ),
    'author': 'DMIS',
    'license': 'LGPL-3',
    'category': 'Custom',
    'depends': ['dms_report'],
    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'views/report_rule_views.xml',
    ],
    'installable': True,
    'application': True,
}
