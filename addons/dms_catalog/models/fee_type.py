from odoo import models, fields


class DmsFeeType(models.Model):
    _name = 'dms.fee.type'
    _description = '費用類型'
    _rec_name = 'name'
    _order = 'name'

    name = fields.Char(string='費用名稱', required=True)
    code = fields.Char(string='費用代碼', help='例：OPEN（開辦費）、SETUP（設定費）')
    active = fields.Boolean(string='啟用', default=True)
