import math

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_TRACKED = ('periods', 'price_base', 'interest_rate', 'setup_fee', 'opening_fee')


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
        string='年利率（%）', digits=(5, 2), default=0.0,
        help='輸入百分比數值，例：1 = 1%，3.5 = 3.5%；無利率填 0')
    setup_fee = fields.Float(
        string='設定費', digits=(12, 0), default=0.0,
        help='一次性收取，不計入每期金額')
    opening_fee = fields.Float(
        string='開辦費', digits=(12, 0), default=0.0,
        help='一次性收取，不計入每期金額')
    monthly_payment = fields.Float(
        string='每期金額', digits=(12, 0),
        compute='_compute_monthly_payment', store=True,
        help='單利公式：基準價 × (1 + 年利率 × 年數) / 期數，四捨五入至整數。'
             '設定費、開辦費為一次性費用，不含在此欄位中。')
    note = fields.Char(string='備註')
    installment_change_note = fields.Char(
        string='異動說明',
        store=False,
        inverse='_inverse_installment_change_note',
        help='本次分期方案修改的原因，儲存後自動記入異動日誌並清空')

    def _inverse_installment_change_note(self):
        """不需儲存；Odoo 透過此 inverse 確保欄位值傳入 write() 的 vals。"""
        pass

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
            # 年金現值公式反解 PMT：PMT = PV × r / (1 - (1+r)^-n)
            # r = 月利率 = 年利率(%) ÷ 12 ÷ 100；利率為 0 時退化為 PV / n
            r = (rec.interest_rate or 0.0) / 100.0 / 12.0
            if r == 0.0:
                rec.monthly_payment = math.floor(base / periods + 0.6)
            else:
                rec.monthly_payment = math.floor(base * r / (1.0 - (1.0 + r) ** (-periods)) + 0.6)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        log_vals_list = []
        for rec, vals in zip(records, vals_list):
            note = vals.get('installment_change_note') or ''
            base_label = '現金價' if rec.price_base == 'cash' else '牌價'
            rate_str = f'{rec.interest_rate:.2f}%' if rec.interest_rate else '0%'
            desc = (
                f'新增 {rec.periods} 期'
                f'（基準：{base_label}，年利率：{rate_str}，'
                f'設定費：{int(rec.setup_fee):,}，開辦費：{int(rec.opening_fee):,}，'
                f'月付金：{int(rec.monthly_payment):,}）'
            )
            log_vals_list.append({
                'product_id': rec.product_id.id,
                'action': 'add',
                'periods': rec.periods,
                'description': desc,
                'note': note,
            })
        if log_vals_list:
            self.env['dms.product.installment.log'].create(log_vals_list)
        # store=False 欄位不寫入 DB，web_read 自動回傳空值，不需 SQL clear
        return records

    def write(self, vals):
        has_tracked = any(k in vals for k in _TRACKED)

        # 從 vals 取使用者輸入的異動說明（vals 是使用者本次輸入的最新值）
        user_note = vals.get('installment_change_note') or ''
        # 取修改前快照
        snapshots = {rec.id: {k: rec[k] for k in _TRACKED} for rec in self}

        result = super().write(vals)

        if has_tracked:
            # 強制清除 ORM cache，確保讀取最新的 computed store 值
            self.invalidate_recordset()
            for rec in self:
                snap = snapshots[rec.id]
                changes = []
                if snap['periods'] != rec.periods:
                    changes.append(f'期數 {snap["periods"]}→{rec.periods}')
                if snap['price_base'] != rec.price_base:
                    old_lbl = '現金價' if snap['price_base'] == 'cash' else '牌價'
                    new_lbl = '現金價' if rec.price_base == 'cash' else '牌價'
                    changes.append(f'計算基準 {old_lbl}→{new_lbl}')
                if snap['interest_rate'] != rec.interest_rate:
                    changes.append(
                        f'年利率 {snap["interest_rate"]:.2f}%→{rec.interest_rate:.2f}%'
                    )
                if snap['setup_fee'] != rec.setup_fee:
                    changes.append(f'設定費 {int(snap["setup_fee"]):,}→{int(rec.setup_fee):,}')
                if snap['opening_fee'] != rec.opening_fee:
                    changes.append(f'開辦費 {int(snap["opening_fee"]):,}→{int(rec.opening_fee):,}')
                if changes:
                    desc = (
                        f'修改 {rec.periods} 期'
                        f'（{"；".join(changes)}，月付金 {int(rec.monthly_payment):,}）'
                    )
                    self.env['dms.product.installment.log'].create({
                        'product_id': rec.product_id.id,
                        'action': 'modify',
                        'periods': rec.periods,
                        'description': desc,
                        'note': user_note,
                    })

        # store=False 欄位不寫入 DB，web_read 自動回傳空值，不需 SQL clear
        return result

    def unlink(self):
        log_vals = []
        for rec in self:
            base_label = '現金價' if rec.price_base == 'cash' else '牌價'
            rate_str = f'{rec.interest_rate:.2f}%' if rec.interest_rate else '0%'
            log_vals.append({
                'product_id': rec.product_id.id,
                'action': 'delete',
                'periods': rec.periods,
                'description': (
                    f'刪除 {rec.periods} 期（{base_label}，{rate_str}，'
                    f'月付金 {int(rec.monthly_payment):,}）'
                ),
            })
        result = super().unlink()
        self.env['dms.product.installment.log'].create(log_vals)
        return result
