from odoo import models, fields


class VehiclePrice(models.Model):
    _name = 'dms.vehicle.price'
    _description = '車款售價'
    _rec_name = 'product_id'
    _order = 'product_id, valid_year_month desc'

    product_id = fields.Many2one(
        'dms.product', string='車款', required=True, ondelete='restrict')
    cash_price = fields.Float(string='現金售價', digits=(12, 0))
    valid_year_month = fields.Char(
        string='有效月份', help='格式：YYYY-MM，例如 2026-03')
    is_promotion = fields.Boolean(string='當月活動')
    active = fields.Boolean(string='啟用', default=True)
    note = fields.Text(string='備註')
    installment_ids = fields.One2many(
        'dms.installment.plan', 'price_id', string='分期方案')
