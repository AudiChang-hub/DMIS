from odoo import models, fields, api
from odoo.exceptions import ValidationError


class DmsCommissionDealerRule(models.Model):
    """車行覆蓋規則：特定車行（可多選）在基礎傭金之上套用公式"""
    _name = 'dms.commission.dealer.rule'
    _description = '車行覆蓋傭金規則'
    _rec_name = 'product_tmpl_id'
    _order = 'product_tmpl_id'

    dealer_ids = fields.Many2many(
        'dms.dealer', 'commission_dealer_rule_dealer_rel',
        'rule_id', 'dealer_id',
        string='適用車行', required=True,
        help='可同時選取多家車行共用相同公式')
    product_tmpl_id = fields.Many2one(
        'dms.product.template', string='車型', required=True,
        ondelete='restrict')
    formula_type = fields.Selection(
        [
            ('base_plus_fixed', '基礎 + 固定加碼'),
            ('base_times_percent', '基礎 × 百分比'),
        ],
        string='公式類型', required=True, default='base_plus_fixed')
    addon_amount = fields.Float(
        string='加碼金額', digits=(12, 0), default=0,
        help='用於「基礎 + 固定加碼」，例如 500 代表每台多給 500 元')
    addon_percent = fields.Float(
        string='加碼百分比（%）', digits=(6, 2), default=0.0,
        help='用於「基礎 × 百分比」，例如輸入 10 代表基礎 × 110%（+10%），輸入 -5 代表 -5%')
    result_preview = fields.Float(
        string='試算結果', digits=(12, 0),
        compute='_compute_result_preview', store=False,
        help='根據基礎傭金規則試算，僅供參考')
    note = fields.Text(string='備註')

    _sql_constraints = [
        ('tmpl_uniq', 'unique(product_tmpl_id)',
         '同一車型只能設定一條覆蓋規則'),
    ]

    @api.depends('formula_type', 'addon_amount', 'addon_percent', 'product_tmpl_id')
    def _compute_result_preview(self):
        for rec in self:
            base_rule = self.env['dms.commission.product.rule'].search(
                [('product_tmpl_id', '=', rec.product_tmpl_id.id)], limit=1)
            base = base_rule.base_amount if base_rule else 0.0
            rec.result_preview = rec.compute_amount(base)

    def compute_amount(self, base_amount):
        """依 formula_type 計算最終傭金"""
        self.ensure_one()
        if self.formula_type == 'base_plus_fixed':
            return base_amount + self.addon_amount
        elif self.formula_type == 'base_times_percent':
            return base_amount * (1 + self.addon_percent / 100.0)
        return base_amount

    @api.constrains('addon_percent')
    def _check_percent(self):
        for rec in self:
            if rec.formula_type == 'base_times_percent' and rec.addon_percent <= -100:
                raise ValidationError('加碼百分比不可小於或等於 -100%（結果會是負數）')
