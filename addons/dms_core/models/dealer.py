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
    owner_name = fields.Char(string='負責人', required=True)
    store_manager = fields.Char(string='店長', required=True)
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
    # New contact fields
    phone_1 = fields.Char(string='電話1')
    phone_2 = fields.Char(string='電話2')
    mobile = fields.Char(string='手機')
    mobile_fax = fields.Char(string='手機/傳真')
    email = fields.Char(string='電子郵件')
    address = fields.Text(string='地址')
    city = fields.Char(string='縣市')
    district = fields.Char(string='鄉鎮市區')
    tags = fields.Many2many('dms.dealer.tag', string='標籤')
    note = fields.Html(string='備註')
    partner_id = fields.Many2one('res.partner', string='Partner (選用)')

    # Price list permissions
    sym_gas_price_list = fields.Boolean(string='三陽油車價格表', default=False)
    sym_ev_price_list = fields.Boolean(string='三陽電車價格表', default=False)
    suzuki_gas_price_list = fields.Boolean(string='台鈴油車價格表', default=False)
    suzuki_ev_price_list = fields.Boolean(string='台鈴電車價格表', default=False)

    # Dispatch capacities
    sym_dispatch_capacity = fields.Integer(string='三陽排車容量')
    suzuki_dispatch_capacity = fields.Integer(string='台鈴排車容量')

    # Groups / activities
    sym_line_group = fields.Boolean(string='三陽LINE群組', default=False)
    suzuki_line_group = fields.Boolean(string='台鈴LINE群組', default=False)
    common_line_group = fields.Boolean(string='通用LINE群組', default=False)
    special_line_group = fields.Boolean(string='特殊LINE群組', default=False)
    holiday_gift = fields.Boolean(string='年節送禮', default=False)

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

    @api.constrains('sym_dispatch_capacity', 'suzuki_dispatch_capacity')
    def _check_capacities_non_negative(self):
        for rec in self:
            for field_name in ('sym_dispatch_capacity', 'suzuki_dispatch_capacity'):
                val = getattr(rec, field_name)
                if val is not None and val < 0:
                    raise ValidationError('%s 不可為負數' % (self._fields[field_name].string or field_name))

    @api.model
    def name_get(self):
        result = []
        for rec in self:
            if rec.code:
                display = '[%s] %s' % (rec.code, rec.name or '')
            else:
                display = rec.name or ''
            result.append((rec.id, display))
        return result

    @api.model
    def name_search(self, name, args=None, operator='ilike', limit=100):
        args = args or []
        terms = [
            ('code', operator, name),
            ('name', operator, name),
            ('short_name', operator, name),
            ('phone_1', operator, name),
            ('phone_2', operator, name),
            ('mobile', operator, name),
            ('mobile_fax', operator, name),
        ]
        # build OR domain
        domain = []
        for term in terms[:-1]:
            domain += ['|', term]
        domain += [terms[-1]]
        return self.search(domain + args, limit=limit).name_get()
