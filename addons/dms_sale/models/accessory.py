from odoo import models, fields


class Accessory(models.Model):
    _name = 'dms.accessory'
    _description = '精品售價'
    _order = 'name'

    name = fields.Char(string='精品名稱', required=True)
    model_number = fields.Char(string='型號')
    unit_price = fields.Float(string='單價', digits=(12, 0))
    install_fee = fields.Float(string='安裝費', digits=(12, 0))
    bundle_name = fields.Char(string='套裝組合')
    valid_from = fields.Date(string='有效起始')
    valid_to = fields.Date(string='有效截止')
    active = fields.Boolean(string='啟用', default=True)
    note = fields.Text(string='備註')
