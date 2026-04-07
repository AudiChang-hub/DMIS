from odoo import models, fields, api


class DmsCommissionDealerRule(models.Model):
    """車行覆蓋規則：特定車行的固定補貼金額，不限車型"""
    _name = 'dms.commission.dealer.rule'
    _description = '車行覆蓋傭金規則'
    _order = 'id'

    name = fields.Char(
        string='名稱', compute='_compute_name', store=True)
    dealer_ids = fields.Many2many(
        'dms.dealer', 'commission_dealer_rule_dealer_rel',
        'rule_id', 'dealer_id',
        string='適用車行', required=True,
        help='選取適用此固定補貼的車行（可多選）')
    addon_amount = fields.Float(
        string='固定加碼金額', digits=(12, 0), default=0,
        help='不限車型，每台銷售固定加碼金額（正數代表加碼，負數代表扣減）')
    note = fields.Text(string='備註')

    @api.depends('dealer_ids')
    def _compute_name(self):
        for rec in self:
            names = rec.dealer_ids.mapped('name')
            rec.name = '、'.join(names) if names else '（未設定車行）'
