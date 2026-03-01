from odoo import models, fields


class VehiclePrice(models.Model):
    _name = 'dms.vehicle.price'
    _description = '車款售價'
    _rec_name = 'product_id'
    _order = 'product_id, installment_periods'

    product_id = fields.Many2one(
        'dms.product', string='車款', required=True, ondelete='restrict')
    dealer_id = fields.Many2one(
        'dms.dealer', string='車行', ondelete='restrict',
        help='留空代表適用全部車行')
    cash_price = fields.Float(string='現金售價', digits=(12, 0))
    installment_periods = fields.Integer(
        string='分期期數', default=0, help='0 = 不適用分期')
    installment_monthly = fields.Float(string='月付金', digits=(12, 0))
    finance_company = fields.Char(string='分期公司')
    valid_year_month = fields.Char(
        string='有效月份', help='格式：YYYY-MM，例如 2026-03')
    is_promotion = fields.Boolean(string='當月活動')
    active = fields.Boolean(string='啟用', default=True)
    note = fields.Text(string='備註')
