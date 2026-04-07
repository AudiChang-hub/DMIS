from odoo import models, fields, api
from odoo.exceptions import ValidationError
import datetime


class DmsCommissionVolumeRule(models.Model):
    """台數現金獎勵規則：達到門檻台數後每台加碼現金"""
    _name = 'dms.commission.volume.rule'
    _description = '台數現金獎勵規則'
    _rec_name = 'name'
    _order = 'name'

    name = fields.Char(string='規則名稱', required=True)
    dealer_ids = fields.Many2many(
        'dms.dealer', 'commission_volume_rule_dealer_rel',
        'rule_id', 'dealer_id',
        string='適用車行',
        help='留空代表通用規則（適用所有車行）')
    brand_id = fields.Many2one(
        'dms.brand', string='限定品牌',
        ondelete='restrict',
        help='留空代表所有品牌；設定後只計算該品牌的台數')
    product_tmpl_ids = fields.Many2many(
        'dms.product.template', 'commission_volume_rule_tmpl_rel',
        'rule_id', 'tmpl_id',
        string='限定車型',
        help='留空代表不限制車型')
    energy_type = fields.Selection(
        [('oil', '油車'), ('electric', '電車')],
        string='限定能源型式',
        help='留空代表油車+電車都計入')
    mode = fields.Selection(
        [
            ('retroactive', '可回溯（達標後補算全部台數）'),
            ('after_threshold', '不可回溯（超門檻後每台才算）'),
        ],
        string='計算模式', required=True, default='retroactive',
        help='retroactive：達到門檻後 1～N 台全部補給；'
             'after_threshold：達到門檻後第 N+1 台起才有')
    min_qty = fields.Integer(
        string='達標門檻（台）', required=True, default=3,
        help='當期結案台數達到此數字後才觸發')
    bonus_per_unit = fields.Float(
        string='每台加碼金額', digits=(12, 0), required=True,
        help='達標後每台訂單額外增加的傭金（TWD）')
    period_type = fields.Selection(
        [
            ('monthly', '月統計（每月重置）'),
            ('custom', '自訂起迄'),
        ],
        string='統計期間', required=True, default='monthly')
    date_from = fields.Date(
        string='起日', help='monthly：規則生效起日；custom：統計起日（必填）')
    date_to = fields.Date(
        string='迄日', help='monthly：規則生效迄日；custom：統計迄日（必填）')
    active = fields.Boolean(string='啟用', default=True)
    note = fields.Text(string='備註')
    rule_type = fields.Selection(
        [('general', '通用規則'), ('specific', '特殊規則')],
        string='規則類型', compute='_compute_rule_type', store=True,
        help='系統自動判斷：適用車行留空為通用規則；有指定車行為特殊規則')

    @api.depends('dealer_ids')
    def _compute_rule_type(self):
        for rec in self:
            rec.rule_type = 'specific' if rec.dealer_ids else 'general'

    @api.constrains('min_qty', 'bonus_per_unit')
    def _check_positive(self):
        for rec in self:
            if rec.min_qty < 1:
                raise ValidationError('達標門檻至少為 1 台')
            if rec.bonus_per_unit <= 0:
                raise ValidationError('每台加碼金額必須大於 0')

    @api.constrains('period_type', 'date_from', 'date_to')
    def _check_custom_dates(self):
        for rec in self:
            if rec.period_type == 'custom':
                if not rec.date_from or not rec.date_to:
                    raise ValidationError('自訂統計期間必須填寫起日與迄日')
                if rec.date_from > rec.date_to:
                    raise ValidationError('起日不能晚於迄日')

    def get_period_range(self, closed_month):
        """依 period_type 回傳 (date_from, date_to)，供計算台數用"""
        self.ensure_one()
        if self.period_type == 'custom':
            return self.date_from, self.date_to
        # monthly：以 closed_month（YYYY-MM）算出當月首末日
        year, month = int(closed_month[:4]), int(closed_month[5:7])
        first_day = datetime.date(year, month, 1)
        if month == 12:
            last_day = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
        else:
            last_day = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
        return first_day, last_day

    def is_applicable_for(self, dealer_id, ref_date):
        """判斷此規則是否適用於指定車行與日期（monthly 模式只看 date_from/to 是否覆蓋）"""
        self.ensure_one()
        if self.dealer_ids and dealer_id not in self.dealer_ids.ids:
            return False
        if self.period_type == 'monthly':
            if self.date_from and ref_date < self.date_from:
                return False
            if self.date_to and ref_date > self.date_to:
                return False
        return True
