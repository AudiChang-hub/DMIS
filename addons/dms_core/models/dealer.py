import logging
from datetime import datetime

from odoo import models, fields, api
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class DealerTag(models.Model):
    _name = 'dms.dealer.tag'
    _description = '車行標籤'

    name = fields.Char(string='標籤名稱', required=True)


class DealerTypeLegacy(models.Model):
    """舊版車行類型（保留以避免 DB migration 失敗，不在新視圖顯示）"""
    _name = 'dms.dealer.type'
    _description = '車行類型（舊）'

    name = fields.Char(string='類型名稱', required=True)
    code = fields.Char(string='代碼', help='短碼 (建議 2 碼)')


class Dealer(models.Model):
    _name = 'dms.dealer'
    _description = '車行'

    code = fields.Char(string='車行代碼', readonly=True, copy=False)
    name = fields.Char(string='店名', required=True)
    owner_name = fields.Char(string='負責人', required=True)
    store_manager = fields.Char(string='店長')
    manager_same_as_owner = fields.Boolean(string='店長同上', default=False)

    store_type_id = fields.Many2one('dms.store_type', string='車行類型')
    brand_ids = fields.Many2many(
        'dms.brand',
        relation='dms_dealer_brand_rel',
        column1='dealer_id',
        column2='brand_id',
        string='品牌',
    )
    active = fields.Boolean(string='啟用', default=True)

    # 聯絡資訊
    phone_1 = fields.Char(string='電話1')
    phone_2 = fields.Char(string='電話2')
    mobile = fields.Char(string='手機')
    mobile_fax = fields.Char(string='手機/傳真')
    email = fields.Char(string='電子信箱')
    address = fields.Text(string='地址')
    note = fields.Text(string='備註')

    # 品牌價格表 (Boolean)
    sym_gas_price_list = fields.Boolean(string='三陽油車價格表', default=False)
    sym_ev_price_list = fields.Boolean(string='三陽電車價格表', default=False)
    suzuki_gas_price_list = fields.Boolean(string='台鈴油車價格表', default=False)
    suzuki_ev_price_list = fields.Boolean(string='台鈴電車價格表', default=False)

    # 排車容量
    sym_dispatch_capacity = fields.Integer(string='三陽排車容量')
    suzuki_dispatch_capacity = fields.Integer(string='台鈴排車容量')

    # 群組/活動
    line_group = fields.Boolean(string='有 LINE 群組', default=False)
    holiday_gift = fields.Boolean(string='年節送禮', default=False)

    # 保留舊欄位（DB backward compatibility，不在新視圖顯示）
    short_name = fields.Char(string='簡稱')
    city = fields.Char(string='縣市')
    district = fields.Char(string='鄉鎮市區')
    phone = fields.Char(string='電話')
    contact_name = fields.Char(string='聯絡人')
    tags = fields.Many2many('dms.dealer.tag', string='標籤')
    sym_price_list = fields.Selection([
        ('none', '無'), ('gas', '油車'), ('ev', '電車'), ('all', '全部'),
    ], string='三陽價格表(舊)', default='none')
    suzuki_price_list = fields.Selection([
        ('none', '無'), ('gas', '油車'), ('ev', '電車'), ('all', '全部'),
    ], string='台鈴價格表(舊)', default='none')

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
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        args = args or []
        if not name:
            return self.search(args, limit=limit).name_get()
        domain = [
            '|', '|', '|', '|', '|', '|', '|',
            ('code', operator, name),
            ('name', operator, name),
            ('phone_1', operator, name),
            ('mobile', operator, name),
            ('owner_name', operator, name),
            ('store_manager', operator, name),
            ('address', operator, name),
            ('brand_ids.name', operator, name),
        ]
        return self.search(domain + args, limit=limit).name_get()

    def _generate_dealer_code(self, store_type_id):
        """依車行類型分類產生代碼：{D|S|N}{YY}{MM}{DD}{seq:02d}"""
        prefix = 'N'
        if store_type_id:
            try:
                st = self.env['dms.store_type'].browse(int(store_type_id))
                if st and st.category == 'dealer':
                    prefix = 'D'
                elif st and st.category == 'exclusive':
                    prefix = 'S'
            except Exception:
                pass
        date_part = datetime.now().strftime('%y%m%d')
        base = prefix + date_part  # e.g. 'D260317'
        # 找出同前綴同日期最大流水碼
        existing = self.search([('code', 'like', base + '%')]).mapped('code')
        max_seq = 0
        for c in existing:
            if len(c) == 9 and c[:7] == base:
                try:
                    seq = int(c[7:])
                    if seq > max_seq:
                        max_seq = seq
                except ValueError:
                    pass
        seq = max_seq + 1
        code = '%s%02d' % (base, seq)
        # 防止極端情況下的重複（競態條件保護）
        while self.search([('code', '=', code)], limit=1):
            seq += 1
            code = '%s%02d' % (base, seq)
        return code

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('manager_same_as_owner') and not vals.get('store_manager'):
                vals['store_manager'] = vals.get('owner_name', '')
            if not vals.get('code'):
                vals['code'] = self._generate_dealer_code(vals.get('store_type_id'))
        return super().create(vals_list)

    @api.onchange('manager_same_as_owner', 'owner_name')
    def _onchange_manager_same(self):
        for rec in self:
            if rec.manager_same_as_owner:
                rec.store_manager = rec.owner_name

    def write(self, vals):
        if vals.get('manager_same_as_owner'):
            owner_val = vals.get('owner_name')
            if owner_val and not vals.get('store_manager'):
                vals['store_manager'] = owner_val
            elif 'store_manager' not in vals:
                for rec in self:
                    vals['store_manager'] = rec.owner_name
                    break
        return super().write(vals)

    def copy(self, default=None):
        default = dict(default or {})
        if 'code' not in default:
            base = self.code or 'COPY'
            candidate = f'{base}-C'
            for n in range(2, 20):
                if not self.search([('code', '=', candidate)], limit=1):
                    break
                candidate = f'{base}-C{n}'
            default['code'] = candidate
        return super().copy(default)
