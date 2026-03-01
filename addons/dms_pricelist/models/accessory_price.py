from odoo import models, fields


class AccessoryPrice(models.Model):
    _name = 'dms.accessory.price'
    _description = '精品售價'
    _rec_name = 'accessory_id'
    _order = 'accessory_id, valid_from desc'

    accessory_id = fields.Many2one(
        'dms.accessory', string='精品', required=True, ondelete='cascade')
    unit_price = fields.Float(string='單價', digits=(12, 0))
    install_fee = fields.Float(string='安裝費', digits=(12, 0))
    bundle_name = fields.Char(string='套裝組合')
    valid_from = fields.Date(string='有效起始')
    valid_to = fields.Date(string='有效截止')
    active = fields.Boolean(string='啟用', default=True)
