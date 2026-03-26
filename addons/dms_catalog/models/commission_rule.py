from odoo import models, fields


class CommissionRule(models.Model):
    _name = 'dms.commission.rule'
    _description = '傭金規則'
    _rec_name = 'dealer_id'
    _order = 'dealer_id, product_template_id, installment_periods'

    dealer_id = fields.Many2one(
        'dms.dealer', string='車行', required=True, ondelete='restrict')
    product_template_id = fields.Many2one(
        'dms.product.template', string='車款型式', ondelete='restrict',
        help='留空代表適用全部車款')
    installment_periods = fields.Integer(
        string='分期期數', default=0, help='0 = 現金')
    commission_amount = fields.Float(string='傭金金額', digits=(12, 0))
    commission_rate = fields.Float(string='傭金比例（%）', digits=(6, 2))
    valid_from = fields.Date(string='有效起始')
    valid_to = fields.Date(string='有效截止')
    active = fields.Boolean(string='啟用', default=True)
    note = fields.Text(string='備註')
