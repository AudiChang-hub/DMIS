from odoo import api, fields, models
from odoo.exceptions import ValidationError


class DmsProductInstallmentLine(models.Model):
    _name = 'dms.product.installment.line'
    _description = '產品分期方案明細'
    _order = 'product_id, rule_id, periods'

    product_id = fields.Many2one(
        'dms.product', string='產品項', required=True,
        ondelete='cascade', index=True)
    rule_id = fields.Many2one(
        'dms.installment.rule', string='分期方案',
        ondelete='set null')
    periods = fields.Integer(
        string='期數', required=True, default=24,
        help='分期期數，例：12、24、36')
    price_base = fields.Selection(
        [('cash', '現金價'), ('list', '牌價')],
        string='計算基準', required=True, default='cash',
        help='月付金以哪個價格為基礎試算')
    interest_rate = fields.Float(
        string='年利率', digits=(5, 4), default=0.0,
        help='年利率（小數），例：0.05 = 5%；無利率填 0')
    setup_fee = fields.Float(
        string='設定費', digits=(12, 0), default=0.0)
    opening_fee = fields.Float(
        string='開辦費', digits=(12, 0), default=0.0)
    monthly_payment = fields.Float(
        string='每期金額', digits=(12, 0),
        compute='_compute_monthly_payment', store=True,
        help='以單利公式：基準價 × (1 + 年利率 × 年數) / 期數，四捨五入至整數')
    note = fields.Char(string='備註')

    _sql_constraints = [
        ('unique_product_periods',
         'unique(product_id, periods)',
         '同一產品項下，相同期數只能設定一筆。'),
    ]

    @api.constrains('periods')
    def _check_periods(self):
        for rec in self:
            if rec.periods <= 0:
                raise ValidationError('期數必須大於 0。')

    @api.depends(
        'product_id.cash_price', 'product_id.list_price',
        'price_base', 'periods', 'interest_rate',
    )
    def _compute_monthly_payment(self):
        for rec in self:
            periods = rec.periods or 0
            if periods <= 0:
                rec.monthly_payment = 0.0
                continue
            if rec.price_base == 'list':
                base = rec.product_id.list_price or 0.0
            else:
                base = rec.product_id.cash_price or 0.0
            rate = rec.interest_rate or 0.0
            years = periods / 12.0
            total = base * (1.0 + rate * years)
            rec.monthly_payment = round(total / periods)
