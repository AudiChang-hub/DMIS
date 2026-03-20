from odoo import models, fields


class Brand(models.Model):
    _name = 'dms.brand'
    _description = '品牌'
    _inherit = ['image.mixin']

    name = fields.Char(string='品牌名稱', required=True)
    active = fields.Boolean(string='啟用', default=True)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', '品牌名稱必須唯一'),
    ]
