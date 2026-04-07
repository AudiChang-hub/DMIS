from odoo import models, fields, api


class DmsCommissionDealerRuleIncentiveLine(models.Model):
    """車行覆蓋規則實物激勵明細：每台結案後附帶的實物品項"""
    _name = 'dms.commission.dealer.rule.incentive.line'
    _description = '車行規則實物激勵明細'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    rule_id = fields.Many2one(
        'dms.commission.dealer.rule', string='所屬規則',
        required=True, ondelete='cascade')
    incentive_type_id = fields.Many2one(
        'dms.incentive.type', string='激勵品項',
        required=True, ondelete='restrict')
    quantity = fields.Float(
        string='每台數量', digits=(6, 2), default=1,
        help='每結一台給出的數量')


class DmsCommissionDealerRule(models.Model):
    """車行覆蓋規則：特定車行的固定補貼金額，可限定品牌與能源型式，並可附帶實物激勵"""
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
    brand_id = fields.Many2one(
        'dms.brand', string='限定品牌',
        ondelete='restrict',
        help='留空代表適用所有品牌')
    energy_type = fields.Selection(
        [('oil', '油車'), ('electric', '電車')],
        string='限定能源型式',
        help='留空代表油車＋電車都適用')
    addon_amount = fields.Float(
        string='固定加碼金額', digits=(12, 0), default=0,
        help='每台銷售固定加碼金額（正數加碼，負數扣減）')
    incentive_line_ids = fields.One2many(
        'dms.commission.dealer.rule.incentive.line', 'rule_id',
        string='實物激勵明細',
        help='每台結案後附帶給出的實物品項（如機油）')
    note = fields.Text(string='備註')

    @api.depends('dealer_ids', 'brand_id', 'energy_type')
    def _compute_name(self):
        for rec in self:
            names = rec.dealer_ids.mapped('name')
            dealer_str = '、'.join(names) if names else '（未設定車行）'
            parts = [dealer_str]
            if rec.brand_id:
                parts.append(rec.brand_id.name)
            if rec.energy_type:
                parts.append(dict(rec._fields['energy_type'].selection).get(rec.energy_type, ''))
            rec.name = ' ／ '.join(parts)

    def is_applicable_for(self, tmpl):
        """判斷此規則是否適用於指定車款（品牌＋能源型式篩選）"""
        self.ensure_one()
        if self.brand_id and tmpl and tmpl.brand_id != self.brand_id:
            return False
        if self.energy_type and tmpl and tmpl.energy_type != self.energy_type:
            return False
        return True
