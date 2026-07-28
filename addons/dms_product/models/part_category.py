from odoo import models, fields


class DmsPartCategory(models.Model):
    """零件分類（油品、濾材、電瓶⋯）"""
    _name = 'dms.part.category'
    _description = '零件分類'
    _order = 'name'

    name = fields.Char(string='分類名稱', required=True)
    active = fields.Boolean(string='啟用', default=True)
