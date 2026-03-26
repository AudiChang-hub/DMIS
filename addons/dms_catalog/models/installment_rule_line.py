from odoo import models, fields


class DmsInstallmentRuleLine(models.Model):
    _name = 'dms.installment.rule.line'
    _description = '分期規則明細'
    _rec_name = 'rule_id'
    _order = 'rule_id, periods'

    rule_id = fields.Many2one(
        'dms.installment.rule', string='所屬規則', required=True, ondelete='cascade')
    periods = fields.Integer(string='期數', required=True)
    monthly_payment = fields.Float(string='月付金', digits=(12, 0))
    fee_ids = fields.One2many(
        'dms.installment.rule.fee', 'rule_line_id', string='費用明細')
