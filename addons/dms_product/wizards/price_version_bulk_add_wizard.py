from odoo import api, fields, models


class DmsPriceVersionBulkAddWizard(models.TransientModel):
    _name = 'dms.price.version.bulk.add.wizard'
    _description = '價目版本批次加入產品項'

    version_id = fields.Many2one(
        'dms.price.version', string='價目版本', required=True, readonly=True)
    existing_product_ids = fields.Many2many(
        'dms.product', string='既有產品項', compute='_compute_existing_product_ids')
    product_ids = fields.Many2many(
        'dms.product',
        'dms_price_version_bulk_add_wizard_product_rel',
        'wizard_id',
        'product_id',
        string='產品項 / SKU',
        domain="[('active', '=', True), ('id', 'not in', existing_product_ids)]",
    )

    @api.depends('version_id')
    def _compute_existing_product_ids(self):
        for record in self:
            record.existing_product_ids = record.version_id.line_ids.mapped('product_id')

    def action_add_lines(self):
        self.ensure_one()
        line_model = self.env['dms.price.line']
        for product in self.product_ids:
            existing = line_model.search([
                ('version_id', '=', self.version_id.id),
                ('product_id', '=', product.id),
            ], limit=1)
            if existing:
                continue
            line_model.create({
                'version_id': self.version_id.id,
                'product_id': product.id,
                'cash_price': 0,
                'list_price': 0,
            })
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }
