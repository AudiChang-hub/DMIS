from odoo import models, fields


class ProductColor(models.Model):
    _name = 'dms.product.color'
    _description = '車款顏色'
    _order = 'product_id, sequence'
    _rec_name = 'name'
    _inherit = ['image.mixin']

    product_id = fields.Many2one(
        'dms.product', string='車款', required=True, ondelete='cascade')
    name = fields.Char(string='顏色名稱', required=True)
    sequence = fields.Integer(string='排序', default=10)
    active = fields.Boolean(string='啟用', default=True)
