from odoo import models, fields


class DmsCommissionVehicleRule(models.Model):
    """車種覆蓋規則：特定車型（可限定車行）在基礎傭金之上固定加碼"""
    _name = 'dms.commission.vehicle.rule'
    _description = '車種覆蓋傭金規則'
    _rec_name = 'product_tmpl_id'
    _order = 'product_tmpl_id'

    dealer_ids = fields.Many2many(
        'dms.dealer', 'commission_vehicle_rule_dealer_rel',
        'rule_id', 'dealer_id',
        string='適用車行（留空 = 全部車行）',
        help='留空代表此車種規則適用於所有車行；若只想針對特定車行，請在此選取')
    product_tmpl_id = fields.Many2one(
        'dms.product.template', string='車型', required=True,
        ondelete='restrict')
    addon_amount = fields.Float(
        string='固定加碼金額', digits=(12, 0), default=0,
        help='此車型每台固定加碼金額（正數加碼，負數扣減）')
    note = fields.Text(string='備註')

    _sql_constraints = [
        ('tmpl_uniq', 'unique(product_tmpl_id)',
         '同一車型只能設定一條車種覆蓋規則'),
    ]

    def compute_amount(self, base_amount):
        """套用車種固定加碼"""
        self.ensure_one()
        return base_amount + self.addon_amount
