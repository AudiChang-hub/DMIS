from odoo import models, fields


class DealerBrandAuth(models.Model):
    _name = 'dms.dealer.brand.auth'
    _description = '車行品牌授權'
    _order = 'dealer_id, brand_id'

    dealer_id = fields.Many2one(
        'dms.dealer', string='車行',
        required=True, ondelete='cascade', index=True,
    )
    brand_id = fields.Many2one(
        'dms.brand', string='品牌',
        required=True, ondelete='restrict',
    )
    auth_type = fields.Selection([
        ('dealer',    '經銷'),
        ('exclusive', '專賣'),
        ('none',      '無授權'),
    ], string='廠商認定類型', required=True, default='none')

    _sql_constraints = [
        ('dealer_brand_uniq', 'unique(dealer_id, brand_id)',
         '同一車行的同一品牌只能設定一次'),
    ]
