from odoo import models, fields


class VisitItem(models.Model):
    _name = 'dms.visit.item'
    _description = '拜訪送出物品'
    _order = 'id'

    visit_id = fields.Many2one(
        'dms.visit', string='拜訪紀錄',
        required=True, ondelete='cascade', index=True,
    )
    product_id = fields.Many2one(
        'dms.product', string='產品',
        required=True, ondelete='restrict',
    )
    quantity = fields.Float(string='數量', default=1.0)
    note = fields.Text(string='備註')
