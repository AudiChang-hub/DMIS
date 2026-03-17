from odoo import models, fields


class StoreType(models.Model):
    _name = 'dms.store_type'
    _description = '車行類型'

    name = fields.Char(string='類型名稱', required=True)
    category = fields.Selection([
        ('dealer', '經銷'),
        ('exclusive', '專賣'),
        ('other', '其他'),
    ], string='分類', required=True, default='other',
       help='決定車行代碼前綴：經銷→D、專賣→S、其他→N')
    active = fields.Boolean(string='啟用', default=True)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', '車行類型名稱必須唯一'),
    ]
