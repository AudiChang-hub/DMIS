from odoo import models, fields


class Accessory(models.Model):
    _name = 'dms.accessory'
    _description = '精品品項'
    _order = 'name'

    name = fields.Char(string='精品名稱', required=True)
    model_number = fields.Char(string='型號')
    active = fields.Boolean(string='啟用', default=True)
    price_ids = fields.One2many(
        'dms.accessory.price', 'accessory_id', string='售價記錄')
