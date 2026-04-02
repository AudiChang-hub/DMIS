from odoo import models, fields, api
from odoo.exceptions import ValidationError


class DmsCommissionProductRule(models.Model):
    """基礎傭金規則：每個車型（template）對應一條通用底數"""
    _name = 'dms.commission.product.rule'
    _description = '基礎傭金規則'
    _rec_name = 'product_tmpl_id'
    _order = 'product_tmpl_id'

    product_tmpl_id = fields.Many2one(
        'dms.product.template', string='車型', required=True,
        ondelete='restrict')
    base_amount = fields.Float(
        string='基礎傭金', digits=(12, 0), required=True,
        help='此車型每台的基礎傭金金額（TWD）')
    note = fields.Text(string='備註')

    _sql_constraints = [
        ('product_tmpl_uniq', 'unique(product_tmpl_id)',
         '同一車型只能設定一條基礎傭金規則'),
    ]

    @api.constrains('base_amount')
    def _check_base_amount(self):
        for rec in self:
            if rec.base_amount < 0:
                raise ValidationError('基礎傭金不可為負數')
