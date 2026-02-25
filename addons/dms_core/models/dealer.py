from odoo import models, fields, api


class Dealer(models.Model):
    _name = 'dms.dealer'
    _description = '車行'

    code = fields.Char(string='車行代碼', required=True)
    name = fields.Char(string='車行名稱', required=True)
    level = fields.Selection([
        ('distributor', '總經銷'),
        ('tier1', '一級'),
        ('tier2', '二級'),
        ('owned', '自營店'),
    ], string='車行層級', default='tier1')
    active = fields.Boolean(string='啟用', default=True)
    contact_name = fields.Char(string='聯絡人')
    phone = fields.Char(string='電話')
    email = fields.Char(string='電子郵件')
    address = fields.Text(string='地址')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', '車行代碼必須唯一')
    ]

    @api.model
    def name_search(self, name, args=None, operator='ilike', limit=100):
        args = args or []
        domain = ['|', '|', ('code', operator, name), ('name', operator, name), ('phone', operator, name)]
        return self.search(domain + args, limit=limit).name_get()
