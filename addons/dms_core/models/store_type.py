from odoo import models, fields


class StoreType(models.Model):
    _name = 'dms.store_type'
    _description = '車行類型'

    name = fields.Char(string='類型名稱', required=True)
    active = fields.Boolean(string='啟用', default=True)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', '車行類型名稱必須唯一'),
    ]
