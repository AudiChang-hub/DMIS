from odoo import models, fields, api
from odoo.exceptions import ValidationError


class DealerTag(models.Model):
    _name = 'dms.dealer.tag'
    _description = '車行標籤'

    name = fields.Char(string='標籤名稱', required=True)


class Dealer(models.Model):
    _name = 'dms.dealer'
    _description = '車行'

    code = fields.Char(string='車行代碼', required=True)
    name = fields.Char(string='車行名稱', required=True)
    short_name = fields.Char(string='簡稱')
    level = fields.Selection([
        ('distributor', '總經銷'),
        ('tier1', '一級'),
        ('tier2', '二級'),
        ('owned', '自營店'),
    ], string='車行層級', default='tier1')
    store_type = fields.Selection([
        ('direct', '直營'),
        ('franchise', '加盟'),
        ('partner', '合作'),
        ('other', '其他'),
    ], string='車行類型')
    parent_id = fields.Many2one('dms.dealer', string='上層車行', ondelete='set null')
    child_ids = fields.One2many('dms.dealer', 'parent_id', string='下層車行')
    active = fields.Boolean(string='啟用', default=True)
    contact_name = fields.Char(string='聯絡人')
    phone = fields.Char(string='電話')
    email = fields.Char(string='電子郵件')
    address = fields.Text(string='地址')
    city = fields.Char(string='縣市')
    district = fields.Char(string='鄉鎮市區')
    tags = fields.Many2many('dms.dealer.tag', string='標籤')
    note = fields.Html(string='備註')
    partner_id = fields.Many2one('res.partner', string='Partner (選用)')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', '車行代碼必須唯一')
    ]

    @api.constrains('parent_id')
    def _check_parent_no_cycle(self):
        for rec in self:
            if not rec.parent_id:
                continue
            parent = rec.parent_id
            if parent == rec:
                raise ValidationError('parent_id 不能指向自己')
            # 檢查循環
            seen = set()
            while parent:
                if parent.id in seen:
                    raise ValidationError('parent_id 造成循環，請檢查上層設定')
                seen.add(parent.id)
                parent = parent.parent_id

    @api.model
    def name_get(self):
        result = []
        for rec in self:
            display = '[%s] %s' % (rec.code or '', rec.name or '')
            result.append((rec.id, display))
        return result

    @api.model
    def name_search(self, name, args=None, operator='ilike', limit=100):
        args = args or []
        domain = ['|', '|', '|', ('code', operator, name), ('name', operator, name), ('phone', operator, name), ('short_name', operator, name)]
        return self.search(domain + args, limit=limit).name_get()
