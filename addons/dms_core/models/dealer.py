from odoo import models, fields


class Dealer(models.Model):
    _name = 'dms.dealer'
    _description = '經銷商'

    name = fields.Char(string='名稱', required=True)
    phone = fields.Char(string='電話')
    email = fields.Char(string='電子郵件')
