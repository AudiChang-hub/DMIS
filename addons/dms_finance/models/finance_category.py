from odoo import models, fields


class FinanceCategory(models.Model):
    _name = 'dms.finance.category'
    _description = '財務類別'
    _order = 'type, sequence, name'
    _rec_name = 'name'

    name = fields.Char(string='類別名稱', required=True)
    code = fields.Char(string='代碼', required=True,
                       help='供系統程式引用的唯一識別碼，請勿任意修改已使用的代碼')
    type = fields.Selection(
        [('income', '收入'), ('expense', '支出')],
        string='類別方向', required=True)
    sequence = fields.Integer(string='排序', default=10)
    active = fields.Boolean(string='啟用', default=True)

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', '類別代碼必須唯一。'),
    ]
