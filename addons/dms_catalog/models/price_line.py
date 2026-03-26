from odoo import models, fields


class DmsPriceLine(models.Model):
    _name = 'dms.price.line'
    _description = '定價明細'
    _rec_name = 'sku_id'
    _order = 'version_id, sku_id'

    version_id = fields.Many2one(
        'dms.price.version', string='定價版本', required=True, ondelete='cascade')
    sku_id = fields.Many2one(
        'dms.product.sku', string='SKU', required=True, ondelete='restrict')
    cash_price = fields.Float(string='現金售價', digits=(12, 0))
    list_price = fields.Float(string='牌價', digits=(12, 0))
    is_promotion = fields.Boolean(string='當期活動價')
    note = fields.Text(string='備註')
    installment_rule_ids = fields.Many2many(
        'dms.installment.rule',
        'dms_price_line_rule_rel',
        'line_id', 'rule_id',
        string='適用分期規則')

    _sql_constraints = [
        ('unique_version_sku',
         'UNIQUE(version_id, sku_id)',
         '同一定價版本中，相同 SKU 的定價明細已存在。'),
    ]
