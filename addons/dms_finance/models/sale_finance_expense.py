from odoo import models, fields


EXPENSE_TYPE_SELECTION = [
    ('credit_card_fee',       '信用卡手續費支出'),
    ('installment_fee',       '分期手續費支出'),
    ('plate_fee_expense',     '牌險費支出'),
    ('plate_selection',       '選號支出'),
    ('used_vehicle',          '中古車支出'),
    ('gift_shipping',         '贈品及運費支出'),
    ('dealer_commission',     '車行傭金支出'),
    ('friendly_dealer_bonus', '友善車行獎金支出'),
    ('first_sale_bonus',      '首賣獎金支出'),
    ('unit_bonus',            '台數獎金支出'),
    ('other_expense',         '其他支出'),
]


class SaleFinanceExpense(models.Model):
    _name = 'dms.sale.finance.expense'
    _description = '財務結算支出明細'
    _order = 'finance_id, id'

    finance_id = fields.Many2one(
        'dms.sale.finance', string='財務結算',
        required=True, ondelete='cascade', index=True)
    type = fields.Selection(
        EXPENSE_TYPE_SELECTION, string='支出類型', required=True)
    amount = fields.Float(string='金額', digits=(12, 0), required=True, default=0)
    note = fields.Char(string='備註')
