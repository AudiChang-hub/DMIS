from odoo import fields, models


class DmsInstallmentRuleFee(models.Model):
    _name = 'dms.installment.rule.fee'
    _description = '分期規則費用明細'
    _order = 'rule_line_id, fee_type_id, id'

    rule_line_id = fields.Many2one(
        'dms.installment.rule.line', string='規則明細', required=True, ondelete='cascade')
    fee_type_id = fields.Many2one(
        'dms.fee.type', string='費用類型', required=True, ondelete='restrict')
    amount = fields.Float(string='金額', digits=(12, 0), required=True)
    charge_mode = fields.Selection(
        [
            ('extra', '外加'),
            ('included', '內含'),
            ('company_absorb', '公司吸收'),
        ],
        string='收費方式',
        required=True,
        default='extra',
    )
    note = fields.Text(string='備註')

    _sql_constraints = [
        (
            'unique_fee_per_rule_line',
            'unique(rule_line_id, fee_type_id)',
            '同一規則明細下，同一費用類型只能有一筆設定。',
        ),
    ]
