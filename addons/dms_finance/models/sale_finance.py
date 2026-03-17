from odoo import models, fields, api
from odoo.exceptions import ValidationError


class SaleFinance(models.Model):
    _name = 'dms.sale.finance'
    _description = '銷售財務結算'
    _rec_name = 'sale_order_id'
    _order = 'sale_order_id desc'

    # ── 主要關聯 ────────────────────────────────────────────
    sale_order_id = fields.Many2one(
        'dms.sale.order', string='銷售訂單',
        required=True, ondelete='restrict', index=True)

    # ── 明細 ────────────────────────────────────────────────
    income_ids = fields.One2many(
        'dms.sale.finance.income', 'finance_id', string='收入明細')
    expense_ids = fields.One2many(
        'dms.sale.finance.expense', 'finance_id', string='支出明細')

    # ── 計算欄位 ─────────────────────────────────────────────
    total_income = fields.Float(
        string='收入合計', digits=(12, 0),
        compute='_compute_totals', store=True)
    total_expense = fields.Float(
        string='支出合計', digits=(12, 0),
        compute='_compute_totals', store=True)
    net_profit = fields.Float(
        string='淨利', digits=(12, 0),
        compute='_compute_totals', store=True)

    # ── 備註 ─────────────────────────────────────────────────
    note = fields.Text(string='備註')

    # ── 唯一性約束 ───────────────────────────────────────────
    _sql_constraints = [
        ('sale_order_unique', 'UNIQUE(sale_order_id)',
         '同一銷售訂單只能建立一筆財務結算記錄。'),
    ]

    # ── 計算 ─────────────────────────────────────────────────
    @api.depends('income_ids.amount', 'expense_ids.amount')
    def _compute_totals(self):
        for rec in self:
            rec.total_income = sum(rec.income_ids.mapped('amount'))
            rec.total_expense = sum(rec.expense_ids.mapped('amount'))
            rec.net_profit = rec.total_income - rec.total_expense

    # ── 建立時自動帶入預設明細 ────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec._populate_default_lines()
        return records

    def _populate_default_lines(self):
        """依據銷售訂單欄位產生預設收入/支出明細（只帶入有值的項目）。"""
        order = self.sale_order_id
        if not order:
            return

        # ── 支出預設 ─────────────────────────────────────────
        expense_defaults = []

        plate_fee = (order.fee_vehicle_registration or 0) + (order.fee_insurance or 0)
        if plate_fee:
            expense_defaults.append({
                'finance_id': self.id,
                'type': 'plate_fee_expense',
                'amount': plate_fee,
                'note': '自動帶入（行照費 + 保險費）',
            })

        if order.fee_plate_selection:
            expense_defaults.append({
                'finance_id': self.id,
                'type': 'plate_selection',
                'amount': order.fee_plate_selection,
                'note': '自動帶入',
            })

        if order.commission:
            expense_defaults.append({
                'finance_id': self.id,
                'type': 'dealer_commission',
                'amount': order.commission,
                'note': '自動帶入',
            })

        if expense_defaults:
            self.env['dms.sale.finance.expense'].create(expense_defaults)

        # ── 收入預設 ─────────────────────────────────────────
        income_defaults = []

        if plate_fee:
            income_defaults.append({
                'finance_id': self.id,
                'type': 'plate_fee_income',
                'amount': plate_fee,
                'note': '自動帶入（行照費 + 保險費）',
            })

        if income_defaults:
            self.env['dms.sale.finance.income'].create(income_defaults)
