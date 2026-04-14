import math
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class DmsProductCreateWizard(models.TransientModel):
    _name = 'dms.product.create.wizard'
    _description = '新增價格表產品項'

    # ── 基本資料（必填） ──────────────────────────────────────────────────
    brand_id = fields.Many2one(
        'dms.brand', string='品牌', required=True, ondelete='restrict')
    name = fields.Char(string='機種名稱', required=True)
    type_name = fields.Char(string='型式')
    energy_type = fields.Selection(
        [('oil', '油車'), ('electric', '電車')],
        string='能源型式',
        required=True,
        default='oil',
    )
    production_year = fields.Char(string='出廠年份', required=True)
    color = fields.Char(string='車色')

    # ── 定價（現金價必填） ─────────────────────────────────────────────────
    suggested_price = fields.Float(string='建議售價', digits=(12, 0), default=0.0)
    cash_discount = fields.Float(string='現金直扣', digits=(12, 0), default=0.0)
    cash_price = fields.Float(string='現金價', digits=(12, 0), required=True)

    # ── 分期價（由 cash_price onchange 自動帶值，可手動覆寫） ─────────────
    installment_12_price = fields.Float(string='12期', digits=(12, 0), default=0.0)
    installment_18_price = fields.Float(string='18期', digits=(12, 0), default=0.0)
    installment_24_price = fields.Float(string='24期', digits=(12, 0), default=0.0)
    installment_36_price = fields.Float(string='36期', digits=(12, 0), default=0.0)
    installment_48_price = fields.Float(string='48期', digits=(12, 0), default=0.0)
    installment_60_price = fields.Float(string='60期', digits=(12, 0), default=0.0)

    # ── 備註 ──────────────────────────────────────────────────────────────
    gift_note = fields.Text(string='顧客贈品')
    fees_note = fields.Text(string='附加費用說明')

    @api.onchange('cash_price')
    def _onchange_cash_price(self):
        p = self.cash_price or 0.0
        if p:
            self.installment_12_price = math.floor(p / 12 + 0.6)
            self.installment_18_price = math.floor(p / 18 + 0.6)
            self.installment_24_price = math.floor(p / 24 + 0.6)
            self.installment_36_price = math.floor(p / 36 + 0.6)
            self.installment_48_price = math.floor(p / 48 + 0.6)
            self.installment_60_price = math.floor(p / 60 + 0.6)
        else:
            self.installment_12_price = 0.0
            self.installment_18_price = 0.0
            self.installment_24_price = 0.0
            self.installment_36_price = 0.0
            self.installment_48_price = 0.0
            self.installment_60_price = 0.0

    def action_save(self):
        self.ensure_one()
        vals = {
            'brand_id': self.brand_id.id,
            'name': self.name,
            'energy_type': self.energy_type,
            'production_year': self.production_year,
            'color': self.color or '',
            'suggested_price': self.suggested_price,
            'cash_discount': self.cash_discount,
            'cash_price': self.cash_price,
            'installment_12_price': self.installment_12_price,
            'installment_18_price': self.installment_18_price,
            'installment_24_price': self.installment_24_price,
            'installment_36_price': self.installment_36_price,
            'installment_48_price': self.installment_48_price,
            'installment_60_price': self.installment_60_price,
            'gift_note': self.gift_note or '',
            'fees_note': self.fees_note or '',
        }
        # template_type_name 透過 type_name 寫入（product_compat 的相容欄位）
        if self.type_name:
            vals['template_type_name'] = self.type_name
        self.env['dms.product'].create(vals)
        return {'type': 'ir.actions.act_window_close'}
