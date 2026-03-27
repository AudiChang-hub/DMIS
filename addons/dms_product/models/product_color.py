from odoo import api, fields, models
from odoo.exceptions import ValidationError


class DmsProductColorCompat(models.Model):
    _inherit = 'dms.product.color'

    template_id = fields.Many2one(
        'dms.product.template',
        string='產品模板',
        index=True,
        ondelete='cascade',
    )
    color_code = fields.Char(string='顏色代碼')

    _sql_constraints = [
        (
            'unique_product_color_name',
            'unique(product_id, name)',
            '同一產品項下，顏色名稱不可重複。',
        ),
    ]

    @api.constrains('product_id', 'template_id')
    def _check_product_template_consistency(self):
        for record in self:
            if record.product_id and record.template_id and record.product_id.template_id != record.template_id:
                raise ValidationError('產品顏色必須隸屬於對應的產品模板。')

    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals_list = []
        for vals in vals_list:
            prepared_vals = dict(vals)
            product_id = prepared_vals.get('product_id')
            if product_id:
                product = self.env['dms.product'].browse(product_id)
                prepared_vals['template_id'] = product.template_id.id or False
            prepared_vals_list.append(prepared_vals)
        records = super().create(prepared_vals_list)
        records.mapped('product_id')._sync_legacy_color_summary()
        return records

    def write(self, vals):
        original_products = self.mapped('product_id')
        result = super().write(vals)
        if 'product_id' in vals:
            for record in self:
                template_id = record.product_id.template_id.id or False
                if record.template_id.id != template_id:
                    super(
                        DmsProductColorCompat,
                        record,
                    ).write({'template_id': template_id})
        (original_products | self.mapped('product_id'))._sync_legacy_color_summary()
        return result

    def unlink(self):
        products = self.mapped('product_id')
        result = super().unlink()
        products._sync_legacy_color_summary()
        return result
