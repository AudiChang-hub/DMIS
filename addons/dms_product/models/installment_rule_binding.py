from odoo import api, fields, models


class DmsInstallmentRuleBinding(models.Model):
    _name = 'dms.installment.rule.binding'
    _description = '分期規則掛接'
    _order = 'product_id, price_version_id desc, id desc'

    product_id = fields.Many2one(
        'dms.product', string='產品項', required=True, ondelete='cascade')
    price_version_id = fields.Many2one(
        'dms.price.version', string='價目版本', required=True, ondelete='cascade')
    rule_id = fields.Many2one(
        'dms.installment.rule', string='分期規則模板', required=True, ondelete='restrict')
    active = fields.Boolean(string='啟用', default=True)
    note = fields.Text(string='備註')

    _sql_constraints = [
        (
            'unique_binding_per_product_version',
            'unique(product_id, price_version_id)',
            '同一產品項在同一價目版本下只能有一筆規則掛接。',
        ),
    ]

    def name_get(self):
        result = []
        for record in self:
            label = " / ".join(
                part for part in [
                    record.product_id.display_name,
                    record.price_version_id.name,
                    record.rule_id.name,
                ] if part
            )
            result.append((record.id, label or '分期規則掛接'))
        return result

    @api.model
    def get_effective_binding(self, product, query_date=None):
        if not product:
            return self.browse()
        if 'dms.price.line' not in self.env.registry.models:
            return self.browse()
        price_line = self.env['dms.price.line'].get_effective_line(
            product, query_date=query_date)
        if not price_line:
            return self.browse()
        return self.search([
            ('product_id', '=', product.id),
            ('price_version_id', '=', price_line.version_id.id),
            ('active', '=', True),
        ], limit=1)
