from odoo import models, fields, api
from odoo.exceptions import ValidationError


class DmsCommissionDealerContractLine(models.Model):
    """車行傭金合約 - 實物激勵明細"""
    _name = 'dms.commission.dealer.contract.line'
    _description = '傭金合約實物明細'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    contract_id = fields.Many2one(
        'dms.commission.dealer.contract', string='所屬合約',
        required=True, ondelete='cascade')
    incentive_type_id = fields.Many2one(
        'dms.incentive.type', string='激勵品項',
        required=True, ondelete='restrict')
    quantity = fields.Float(
        string='每台數量', digits=(6, 2), default=1,
        help='每結一台給出的數量')


class DmsCommissionDealerContract(models.Model):
    """車行傭金合約：整合現金傭金與實物激勵，一張表設定完畢"""
    _name = 'dms.commission.dealer.contract'
    _description = '車行傭金合約'
    _rec_name = 'display_name'
    _order = 'dealer_id, brand_id'

    dealer_id = fields.Many2one(
        'dms.dealer', string='車行', required=True, ondelete='restrict', index=True)
    brand_id = fields.Many2one(
        'dms.brand', string='品牌',
        ondelete='restrict', index=True,
        help='留空代表此合約適用該車行旗下所有品牌')
    cash_commission = fields.Float(
        string='每台現金傭金', digits=(12, 0), required=True,
        help='每結案一台，撥給業務的現金傭金金額（已含所有調整）')
    incentive_line_ids = fields.One2many(
        'dms.commission.dealer.contract.line', 'contract_id',
        string='實物激勵明細')
    date_from = fields.Date(string='生效起日', help='留空代表無限制')
    date_to = fields.Date(string='生效迄日', help='留空代表無限制')
    active = fields.Boolean(string='啟用', default=True)
    note = fields.Text(string='備註')

    display_name = fields.Char(
        string='顯示名稱', compute='_compute_display_name', store=True)

    _sql_constraints = [
        ('dealer_brand_uniq', 'unique(dealer_id, brand_id)',
         '同一車行＋品牌組合只能有一份合約'),
    ]

    @api.depends('dealer_id', 'brand_id')
    def _compute_display_name(self):
        for rec in self:
            dealer = rec.dealer_id.name or ''
            brand = rec.brand_id.name or '（全品牌）'
            rec.display_name = f'{dealer} — {brand}'

    @api.constrains('cash_commission')
    def _check_cash(self):
        for rec in self:
            if rec.cash_commission < 0:
                raise ValidationError('每台現金傭金不可為負數')

    def is_applicable_for(self, date):
        """判斷此合約在指定日期是否有效"""
        self.ensure_one()
        if self.date_from and date < self.date_from:
            return False
        if self.date_to and date > self.date_to:
            return False
        return True
