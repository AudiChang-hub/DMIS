{
    'name': 'DMS Core',
    'version': '16.0.1.0.0',
    'summary': '最小車行管理示範',
    'description': '提供 dealer（車行）模型與基本 view，作為專案骨架示範。',
    'author': 'DMIS',
    'license': 'LGPL-3',
    'category': 'Custom',
    'depends': ['base'],
    'data': [
        'security/dms_security.xml',
        'security/ir.model.access.csv',
        'views/dealer_views.xml',
        'data/seed.xml',
    ],
    'installable': True,
    'application': True,
}
