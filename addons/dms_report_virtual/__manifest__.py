{
    'name': '報表虛擬欄位',
    'version': '16.0.1.0.0',
    'summary': '在 UI 中定義計算欄位規則，無需改程式即可在報表中分群統計',
    'description': (
        '允許分析人員透過關鍵字、正則或 Python 表達式定義「虛擬欄位」，'
        '將原始欄位值映射至自訂分類，並整合至動態報表規則（dms_report_rule）做分群統計。'
    ),
    'author': 'DMIS',
    'license': 'LGPL-3',
    'category': 'Custom',
    'depends': ['dms_report_rule'],
    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'views/report_virtual_field_views.xml',
        'views/report_rule_extend_views.xml',
        'views/vf_test_wizard_views.xml',
        'views/vf_preview_wizard_views.xml',
    ],
    'installable': True,
    'application': True,
}
