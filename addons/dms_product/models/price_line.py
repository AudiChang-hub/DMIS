from odoo import api, fields, models


class DmsPriceLine(models.Model):
    _name = 'dms.price.line'
    _description = '價格基準'
    _order = 'version_id desc, id desc'

    version_id = fields.Many2one(
        'dms.price.version', string='價目版本', required=True, ondelete='cascade')
    product_id = fields.Many2one(
        'dms.product', string='產品項 / SKU', required=True, ondelete='restrict')
    cash_price = fields.Float(string='現金價', digits=(12, 0), required=True)
    list_price = fields.Float(string='牌價', digits=(12, 0), required=True)
    note = fields.Text(string='備註')

    _sql_constraints = [
        (
            'unique_price_line_per_version_product',
            'unique(version_id, product_id)',
            '同一價目版本下，同一產品項只能有一筆價格基準。',
        ),
    ]

    @api.model
    def get_effective_line(self, product, query_date=None):
        if not product:
            return self.browse()
        query_date = query_date or fields.Date.context_today(self)
        lines = self.search([
            ('product_id', '=', product.id),
            ('version_id.state', 'in', ['effective', 'archive']),
            ('version_id.effective_date', '<=', query_date),
        ])
        if not lines:
            return self.browse()
        return lines.sorted(
            key=lambda line: (
                line.version_id.effective_date or fields.Date.from_string('1900-01-01'),
                line.version_id.id,
                line.id,
            ),
            reverse=True,
        )[:1]
