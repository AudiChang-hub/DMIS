from odoo import fields, models


class DmsFeeType(models.Model):
    _name = 'dms.fee.type'
    _description = '費用類型'
    _order = 'name, id'

    name = fields.Char(string='費用名稱', required=True)
    code = fields.Char(string='內部代碼', required=True)
    active = fields.Boolean(string='啟用', default=True)
    note = fields.Text(string='備註')

    _sql_constraints = [
        ('unique_fee_type_code', 'unique(code)', '費用類型代碼不可重複。'),
        ('unique_fee_type_name', 'unique(name)', '費用類型名稱不可重複。'),
    ]
