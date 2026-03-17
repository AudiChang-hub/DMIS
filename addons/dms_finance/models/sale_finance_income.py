from odoo import models, fields


INCOME_TYPE_SELECTION = [
    ('plate_fee_income',       '牌險費收入'),
    ('handling_income',        '代辦費收入'),
    ('scrap_handling_income',  '報廢代辦收入'),
    ('plate_selection_income', '選號收入'),
    ('used_vehicle_income',    '中古車收入'),
    ('scrap_vehicle_income',   '報廢車收入'),
    ('service_fee_income',     '手續費收入'),
    ('yamaha_bonus_income',    '山葉獎金收入'),
    ('friendly_dealer_income', '友善車行獎金收入'),
    ('other_income',           '其他收入'),
    ('actual_sales_incentive', '實銷獎勵金'),
    ('promo_subsidy',          '促銷補助金'),
    ('installment_subsidy',    '分期補貼息'),
    ('insurance_commission',   '強制險傭金收入'),
    ('credit_card_commission', '信用卡傭金收入'),
]


class SaleFinanceIncome(models.Model):
    _name = 'dms.sale.finance.income'
    _description = '財務結算收入明細'
    _order = 'finance_id, id'

    finance_id = fields.Many2one(
        'dms.sale.finance', string='財務結算',
        required=True, ondelete='cascade', index=True)
    type = fields.Selection(
        INCOME_TYPE_SELECTION, string='收入類型', required=True)
    amount = fields.Float(string='金額', digits=(12, 0), required=True, default=0)
    note = fields.Char(string='備註')
