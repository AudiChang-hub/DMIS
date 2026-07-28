from odoo import models, fields, api
from odoo.exceptions import ValidationError


class DmsIncentiveRule(models.Model):
    """激勵觸發規則：定義何種條件給予哪種激勵"""
    _name = 'dms.incentive.rule'
    _description = '激勵觸發規則'
    _rec_name = 'name'
    _order = 'name'

    name = fields.Char(string='規則名稱', required=True)
    incentive_type_id = fields.Many2one(
        'dms.incentive.type', string='激勵品項', required=True,
        ondelete='restrict')
    dealer_ids = fields.Many2many(
        'dms.dealer', 'incentive_rule_dealer_rel',
        'rule_id', 'dealer_id',
        string='適用車行',
        help='留空代表適用所有車行')
    product_tmpl_ids = fields.Many2many(
        'dms.product.template', 'incentive_rule_tmpl_rel',
        'rule_id', 'tmpl_id',
        string='限定車型',
        help='留空代表不限制車型')
    trigger = fields.Selection(
        [
            ('per_unit', '每台結案'),
            ('volume', '月達門檻'),
        ],
        string='觸發條件', required=True, default='per_unit')
    min_qty = fields.Integer(
        string='門檻台數', default=1,
        help='僅 trigger=volume 時使用')
    qty_per_trigger = fields.Integer(
        string='每次給予數量', default=1, required=True)
    date_from = fields.Date(string='生效起日')
    date_to = fields.Date(string='生效迄日')
    active = fields.Boolean(string='啟用', default=True)
    note = fields.Text(string='備註')

    @api.constrains('qty_per_trigger', 'min_qty', 'trigger')
    def _check_values(self):
        for rec in self:
            if rec.qty_per_trigger < 1:
                raise ValidationError('每次給予數量至少為 1')
            if rec.trigger == 'volume' and rec.min_qty < 1:
                raise ValidationError('門檻台數至少為 1')

    def is_applicable_for(self, dealer_id, tmpl_id, date):
        """判斷此規則是否適用於指定車行、車型、日期"""
        self.ensure_one()
        if self.dealer_ids and dealer_id not in self.dealer_ids.ids:
            return False
        if self.product_tmpl_ids and tmpl_id not in self.product_tmpl_ids.ids:
            return False
        if self.date_from and date < self.date_from:
            return False
        if self.date_to and date > self.date_to:
            return False
        return True
