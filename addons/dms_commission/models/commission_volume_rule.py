from odoo import models, fields, api
from odoo.exceptions import ValidationError


class DmsCommissionVolumeRule(models.Model):
    """台數獎金規則：當月達到門檻台數後每台加碼"""
    _name = 'dms.commission.volume.rule'
    _description = '台數獎金規則'
    _rec_name = 'name'
    _order = 'name'

    name = fields.Char(string='規則名稱', required=True)
    dealer_ids = fields.Many2many(
        'dms.dealer', 'commission_volume_rule_dealer_rel',
        'rule_id', 'dealer_id',
        string='適用車行',
        help='留空代表適用所有車行')
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
    min_qty = fields.Integer(
        string='達標門檻（台）', required=True, default=3,
        help='當月結案台數達到此數字後才觸發加碼')
    bonus_per_unit = fields.Float(
        string='每台加碼金額', digits=(12, 0), required=True,
        help='達標後每台訂單額外增加的傭金（TWD）')
    date_from = fields.Date(string='生效起日', help='留空代表無限制')
    date_to = fields.Date(string='生效迄日', help='留空代表無限制')
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

    def is_applicable_for(self, dealer_id, date):
        """判斷此規則是否適用於指定車行與日期"""
        self.ensure_one()
        if self.dealer_ids and dealer_id not in self.dealer_ids.ids:
            return False
        if self.date_from and date < self.date_from:
            return False
        if self.date_to and date > self.date_to:
            return False
        return True
