from odoo import api, fields, models
from odoo.exceptions import ValidationError


class DmsInstallmentRuleLine(models.Model):
    _name = 'dms.installment.rule.line'
    _description = '分期規則明細'
    _order = 'rule_id, period_from, id'

    rule_id = fields.Many2one(
        'dms.installment.rule', string='規則模板', required=True, ondelete='cascade')
    period_from = fields.Integer(string='起始期數', required=True)
    period_to = fields.Integer(string='結束期數', required=True)
    price_basis = fields.Selection(
        [('cash', '現金價'), ('list', '牌價')],
        string='價格基準',
        required=True,
        default='cash',
    )
    note = fields.Text(string='備註')
    fee_ids = fields.One2many(
        'dms.installment.rule.fee', 'rule_line_id', string='費用明細')

    @api.constrains('period_from', 'period_to')
    def _check_period_range(self):
        for record in self:
            if record.period_from <= 0 or record.period_to <= 0:
                raise ValidationError('分期期數必須大於 0。')
            if record.period_from > record.period_to:
                raise ValidationError('起始期數不可大於結束期數。')

    @api.constrains('rule_id', 'period_from', 'period_to')
    def _check_period_overlap(self):
        for record in self:
            if not record.rule_id:
                continue
            overlap = self.search([
                ('rule_id', '=', record.rule_id.id),
                ('id', '!=', record.id),
                ('period_from', '<=', record.period_to),
                ('period_to', '>=', record.period_from),
            ], limit=1)
            if overlap:
                raise ValidationError('同一分期規則模板下，期數區間不可重疊。')
