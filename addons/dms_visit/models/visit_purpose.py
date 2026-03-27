from odoo import models, fields


class VisitPurpose(models.Model):
    _name = 'dms.visit.purpose'
    _description = '拜訪目的類別'
    _order = 'sequence, name'

    name = fields.Char(string='目的名稱', required=True)
    code = fields.Char(string='短碼')
    sequence = fields.Integer(string='排序', default=10)
    active = fields.Boolean(string='啟用', default=True)
