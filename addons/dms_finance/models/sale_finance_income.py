from odoo import models, fields


class SaleFinanceIncome(models.Model):
    _name = 'dms.sale.finance.income'
    _description = '財務結算收入明細'
    _order = 'finance_id, sequence, id'

    finance_id = fields.Many2one(
        'dms.sale.finance', string='財務結算',
        required=True, ondelete='cascade', index=True)
    category_id = fields.Many2one(
        'dms.finance.category', string='收入類別',
        required=True, ondelete='restrict',
        domain=[('type', '=', 'income')])
    sequence = fields.Integer(string='排序', default=10)
    amount = fields.Float(string='金額', digits=(12, 0), required=True, default=0)
    note = fields.Char(string='備註')
