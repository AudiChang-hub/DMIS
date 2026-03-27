from odoo import api, fields, models


class DmsProductCompat(models.Model):
    _inherit = 'dms.product'

    template_id = fields.Many2one(
        'dms.product.template', string='產品模板', ondelete='restrict')
    internal_code = fields.Char(string='內部唯一代碼', index=True, copy=False)
    production_year = fields.Integer(string='出廠年份')

    _sql_constraints = [
        ('unique_internal_code', 'unique(internal_code)', '內部唯一代碼不可重複。'),
    ]

    def _parse_year_value(self, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return False

    def _build_generated_code(self):
        self.ensure_one()
        return f"SKU-{self.id:05d}"

    def _prepare_template_sync_vals(self):
        self.ensure_one()
        vals = {}
        if self.template_id:
            vals['brand_id'] = self.template_id.brand_id.id
            vals['name'] = self.template_id.family_name
            vals['model'] = self.template_id.model_name or False
            vals['energy_type'] = self.template_id.energy_type
        if self.production_year and str(self.production_year) != (self.year or ''):
            vals['year'] = str(self.production_year)
        return vals

    @api.model
    def _prepare_create_vals_from_template(self, vals):
        if not vals.get('template_id'):
            return vals
        template = self.env['dms.product.template'].browse(vals['template_id'])
        if not template.exists():
            return vals
        prepared = dict(vals)
        prepared.setdefault('brand_id', template.brand_id.id)
        prepared.setdefault('name', template.family_name)
        prepared.setdefault('model', template.model_name or False)
        prepared.setdefault('energy_type', template.energy_type)
        if prepared.get('production_year') and not prepared.get('year'):
            prepared['year'] = str(prepared['production_year'])
        return prepared

    def _ensure_template_from_legacy(self):
        self.ensure_one()
        if self.template_id:
            return self.template_id
        if not (self.brand_id and self.name and self.energy_type):
            return self.env['dms.product.template'].browse()
        template = self.env['dms.product.template']._find_or_create_from_legacy(self)
        return template

    def _sync_compat_fields(self):
        if self.env.context.get('skip_product_compat_sync'):
            return
        for record in self:
            vals = {}
            template = record.template_id or record._ensure_template_from_legacy()
            if template and record.template_id != template:
                vals['template_id'] = template.id
            if not record.internal_code:
                vals['internal_code'] = record._build_generated_code()
            if not record.production_year:
                parsed_year = record._parse_year_value(record.year)
                if parsed_year:
                    vals['production_year'] = parsed_year
            if template:
                vals.update(record._prepare_template_sync_vals())
            if vals:
                super(
                    DmsProductCompat,
                    record.with_context(skip_product_compat_sync=True),
                ).write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._prepare_create_vals_from_template(vals) for vals in vals_list]
        records = super().create(vals_list)
        records._sync_compat_fields()
        return records

    def write(self, vals):
        result = super().write(vals)
        tracked_fields = {
            'template_id', 'brand_id', 'name', 'model', 'year', 'energy_type',
            'production_year', 'internal_code',
        }
        if tracked_fields.intersection(vals):
            self._sync_compat_fields()
        return result

    @api.model
    def _run_product_backfill(self):
        products = self.with_context(skip_product_compat_sync=False).search([])
        products._sync_compat_fields()
