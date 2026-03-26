from odoo import models, fields


class DmsInstallmentRule(models.Model):
    _name = 'dms.installment.rule'
    _description = '分期規則範本'
    _rec_name = 'name'
    _order = 'name'

    name = fields.Char(string='規則名稱', required=True)
    finance_company = fields.Char(string='分期公司')
    active = fields.Boolean(string='啟用', default=True)
    note = fields.Text(string='備註')
    line_ids = fields.One2many(
        'dms.installment.rule.line', 'rule_id', string='分期明細')
