from odoo import models, fields


class DmsInstallmentRuleFee(models.Model):
    _name = 'dms.installment.rule.fee'
    _description = '分期費用明細'
    _rec_name = 'fee_type_id'
    _order = 'rule_line_id, fee_type_id'

    rule_line_id = fields.Many2one(
        'dms.installment.rule.line', string='所屬明細行',
        required=True, ondelete='cascade')
    fee_type_id = fields.Many2one(
        'dms.fee.type', string='費用類型', required=True, ondelete='restrict')
    amount = fields.Float(string='金額', digits=(12, 0))
    charge_method = fields.Selection(
        [('flat', '固定金額'), ('rate', '比例（%）')],
        string='計費方式', default='flat', required=True)
