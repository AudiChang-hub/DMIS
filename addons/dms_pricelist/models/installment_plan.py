from odoo import models, fields


class InstallmentPlan(models.Model):
    _name = 'dms.installment.plan'
    _description = '分期方案'
    _rec_name = 'price_id'
    _order = 'price_id, installment_periods'

    price_id = fields.Many2one(
        'dms.vehicle.price', string='車款售價', required=True, ondelete='cascade')
    installment_periods = fields.Integer(string='期數', required=True)
    installment_monthly = fields.Float(string='月付金', digits=(12, 0))
    finance_company = fields.Char(string='分期公司')
    active = fields.Boolean(string='啟用', default=True)
