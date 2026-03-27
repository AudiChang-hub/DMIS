import re

from odoo import api, fields, models


LEGACY_GENERATED_CODE_PATTERN = re.compile(r'^SKU-\d{5}$')


class DmsProductCompat(models.Model):
    _inherit = 'dms.product'

    template_id = fields.Many2one(
        'dms.product.template', string='產品模板', ondelete='restrict')
    internal_code = fields.Char(string='內部唯一代碼', index=True, copy=False)
    production_year = fields.Char(string='出廠年份')

    _sql_constraints = [
        ('unique_internal_code', 'unique(internal_code)', '內部唯一代碼不可重複。'),
    ]

    def _normalize_year_value(self, value):
        if value in (False, None, ''):
            return False
        normalized = str(value).strip().replace(',', '')
        return normalized or False

    def _sanitize_code_part(self, value):
        token = re.sub(r'[^A-Z0-9]+', '-', (value or '').upper()).strip('-')
        return token

    def _build_code_base(self):
        self.ensure_one()
        model_token = self._sanitize_code_part(
            self.model or self.template_id.model_name or self.name or self.template_id.family_name
        )
        year_value = self._normalize_year_value(self.production_year or self.year)
        year_token = self._sanitize_code_part(year_value) if year_value else ''
        parts = [part for part in [model_token, year_token] if part]
        return "-".join(parts)

    def _has_legacy_generated_code(self):
        self.ensure_one()
        return bool(LEGACY_GENERATED_CODE_PATTERN.match(self.internal_code or ''))

    def _build_generated_code(self):
        self.ensure_one()
        base_code = self._build_code_base()
        if not base_code:
            return f"SKU-{self.id:05d}"
        candidate = base_code
        suffix = 2
        while self.with_context(active_test=False).search_count([
            ('internal_code', '=', candidate),
            ('id', '!=', self.id),
        ]):
            candidate = f"{base_code}-{suffix:02d}"
            suffix += 1
        return candidate

    def _prepare_template_sync_vals(self):
        self.ensure_one()
        vals = {}
        if self.template_id:
            vals['brand_id'] = self.template_id.brand_id.id
            vals['name'] = self.template_id.family_name
            vals['model'] = self.template_id.model_name or False
            vals['energy_type'] = self.template_id.energy_type
        normalized_year = self._normalize_year_value(self.production_year)
        if normalized_year and normalized_year != (self.year or ''):
            vals['year'] = normalized_year
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
            prepared['year'] = self._normalize_year_value(prepared['production_year'])
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
            if not record.internal_code or record._has_legacy_generated_code():
                vals['internal_code'] = record._build_generated_code()
            normalized_production_year = record._normalize_year_value(record.production_year)
            if normalized_production_year != (record.production_year or False):
                vals['production_year'] = normalized_production_year
            if not normalized_production_year:
                normalized_year = record._normalize_year_value(record.year)
                if normalized_year:
                    vals['production_year'] = normalized_year
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

    def _register_hook(self):
        result = super()._register_hook()
        self._run_product_backfill()
        return result
