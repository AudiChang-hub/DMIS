import logging
from datetime import datetime
import random

from odoo import models, fields, api
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class DealerTag(models.Model):
    _name = 'dms.dealer.tag'
    _description = '車行標籤'

    name = fields.Char(string='標籤名稱', required=True)


class DealerType(models.Model):
    _name = 'dms.dealer.type'
    _description = '車行類型'

    name = fields.Char(string='類型名稱', required=True)
    code = fields.Char(string='代碼', help='短碼 (建議 2 碼)，會用於自動產生車行代碼')


class Brand(models.Model):
    _name = 'dms.brand'
    _description = '品牌'

    name = fields.Char(string='品牌名稱', required=True)


class Dealer(models.Model):
    _name = 'dms.dealer'
    _description = '車行'

    code = fields.Char(string='車行代碼', required=True)
    name = fields.Char(string='車行名稱', required=True)
    short_name = fields.Char(string='簡稱')
    owner_name = fields.Char(string='負責人', required=True)
    store_manager = fields.Char(string='店長', required=True)
    # 原先的 level/parent/child/ store_type 被調整
    # 車行類型改為可管理的 model，並支援選品牌
    store_type_id = fields.Many2one('dms.dealer.type', string='車行類型')
    brand_ids = fields.Many2many('dms.brand', string='品牌', help='適用品牌（可多選）')
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

    # Price list: 改為可選類型（無 / 油車 / 電車 / 全部）
    sym_price_list = fields.Selection([
        ('none', '無'),
        ('gas', '油車'),
        ('ev', '電車'),
        ('all', '全部'),
    ], string='三陽價格表', default='none')
    suzuki_price_list = fields.Selection([
        ('none', '無'),
        ('gas', '油車'),
        ('ev', '電車'),
        ('all', '全部'),
    ], string='台鈴價格表', default='none')

    # Dispatch capacities
    sym_dispatch_capacity = fields.Integer(string='三陽排車容量')
    suzuki_dispatch_capacity = fields.Integer(string='台鈴排車容量')

    # Groups / activities
    line_group = fields.Boolean(string='有 LINE 群組', default=False)
    holiday_gift = fields.Boolean(string='年節送禮', default=False)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', '車行代碼必須唯一')
    ]

    # 移除 parent/child 的循環檢查，已不再使用 parent_id

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

    @api.model
    def create(self, vals):
        # 若未提供 code，嘗試自動產生：type.code(2) + YYMMDD (6) -> 共 8 碼
        if not vals.get('code'):
            type_code = 'XX'
            t_id = vals.get('store_type_id')
            if t_id:
                try:
                    t = self.env['dms.dealer.type'].browse(int(t_id))
                    if t and t.code:
                        type_code = (t.code or 'XX')[:2].upper()
                except Exception:
                    pass
            date_part = datetime.now().strftime('%y%m%d')
            base = (type_code[:2] + date_part)[:8]
            code = base
            # 確保唯一（簡單嘗試幾次）
            for attempt in range(10):
                if not self.search([('code', '=', code)], limit=1):
                    break
                # 若重複，加入隨機尾碼替換最後 1-2 碼
                suffix = str(random.randint(0, 99)).zfill(2)
                code = (base[:-2] + suffix)[:8]
            vals['code'] = code
        return super(Dealer, self).create(vals)

    def fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
        # 使用預設行為，移除自建的 arch 注入邏輯以回歸 Odoo 內建欄位選取
        return super(Dealer, self).fields_view_get(view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)


    # 移除自建的 Wizard、User 設定欄位與臨時 view 流程，回歸 Odoo 內建欄位選取功能
