from odoo import models, fields


class FeeSchedule(models.Model):
    _name = 'dms.fee.schedule'
    _description = '牌險費率'
    _rec_name = 'product_id'
    _order = 'product_id, valid_from desc'

    product_id = fields.Many2one(
        'dms.product', string='車款', required=True, ondelete='restrict')
    fee_registration = fields.Float(string='領牌費', digits=(12, 0))
    fee_compulsory_insurance = fields.Float(string='強制險', digits=(12, 0))
    fee_agency = fields.Float(string='代辦費', digits=(12, 0))
    valid_from = fields.Date(string='有效起始')
    valid_to = fields.Date(string='有效截止')
    active = fields.Boolean(string='啟用', default=True)
    note = fields.Text(string='備註')
