from odoo import fields, models


class DmsProductPriceLog(models.Model):
    _name = 'dms.product.price.log'
    _description = '產品價格異動日誌'
    _order = 'changed_at desc, id desc'

    product_id = fields.Many2one(
        'dms.product', string='產品項',
        required=True, ondelete='cascade', index=True)
    changed_at = fields.Datetime(
        string='異動時間', required=True, readonly=True,
        default=fields.Datetime.now)
    user_id = fields.Many2one(
        'res.users', string='操作者',
        required=True, readonly=True,
        default=lambda self: self.env.uid)
    old_cash_price = fields.Float(
        string='舊現金價', digits=(12, 0), readonly=True)
    new_cash_price = fields.Float(
        string='新現金價', digits=(12, 0), readonly=True)
    old_list_price = fields.Float(
        string='舊牌價', digits=(12, 0), readonly=True)
    new_list_price = fields.Float(
        string='新牌價', digits=(12, 0), readonly=True)
    note = fields.Char(string='異動說明', readonly=True)
