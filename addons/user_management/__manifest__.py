{
    'name': '使用者管理',
    'version': '16.0.1.0.0',
    'summary': '自訂存取群組，以菜單白名單控制各使用者可見頁面',
    'description': (
        '提供 um.access.group（自訂存取群組）模型，讓管理者勾選群組可見的菜單，'
        '並將使用者指派到群組；使用者可見菜單取所有群組聯集。'
        '若使用者未指派任何群組，行為與原始 Odoo 相同。'
        '管理介面僅系統管理員可見，不修改任何現有群組或 ACL 設定。'
    ),
    'author': 'DMIS',
    'license': 'LGPL-3',
    'category': 'Custom',
    'depends': ['base', 'web', 'mail', 'stock', 'dms_finance', 'dms_report_ds'],
    'data': [
        'security/ir.model.access.csv',
        'views/um_access_group_views.xml',
        'views/res_users_inherit.xml',
        'views/um_audit_log_views.xml',
        'views/um_menu_views.xml',
        'data/hide_menus.xml',
    ],
    'installable': True,
    'application': True,
    'post_init_hook': 'post_init_hook',
    'post_migrate': 'post_migrate_hook',
}
