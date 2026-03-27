from datetime import date

from odoo import api, fields, models


class DmsPriceVersion(models.Model):
    _name = 'dms.price.version'
    _description = '價目版本'
    _order = 'effective_date desc, id desc'

    name = fields.Char(string='版本名稱', required=True)
    effective_date = fields.Date(string='生效日', required=True)
    state = fields.Selection(
        [('draft', '草稿'), ('effective', '生效'), ('archive', '封存')],
        string='狀態',
        required=True,
        default='draft',
    )
    note = fields.Text(string='備註')
    line_ids = fields.One2many(
        'dms.price.line', 'version_id', string='價格基準')
    binding_ids = fields.One2many(
        'dms.installment.rule.binding', 'price_version_id', string='規則掛接')

    _sql_constraints = [
        ('unique_price_version_name', 'unique(name)', '價目版本名稱不可重複。'),
    ]

    def action_open_bulk_add_products_wizard(self):
        self.ensure_one()
        wizard = self.env['dms.price.version.bulk.add.wizard'].create({
            'version_id': self.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': '批次加入產品項',
            'res_model': 'dms.price.version.bulk.add.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    @api.model
    def _parse_legacy_effective_date(self, value):
        if value:
            try:
                year_str, month_str = value.split('-', 1)
                return date(int(year_str), int(month_str), 1)
            except (TypeError, ValueError):
                pass
        return fields.Date.context_today(self)

    @api.model
    def _find_or_create_legacy_version(self, legacy_price):
        effective_date = self._parse_legacy_effective_date(legacy_price.valid_year_month)
        label = f"Legacy {legacy_price.valid_year_month or fields.Date.to_string(effective_date)}"
        version = self.search([
            ('name', '=', label),
            ('effective_date', '=', effective_date),
        ], limit=1)
        if version:
            return version
        return self.create({
            'name': label,
            'effective_date': effective_date,
            'state': 'effective',
            'note': '由 legacy dms.vehicle.price 自動回填',
        })

    @api.model
    def _run_legacy_backfill(self):
        if 'dms.vehicle.price' not in self.env.registry.models:
            return
        price_line_model = self.env['dms.price.line']
        legacy_prices = self.env['dms.vehicle.price'].search([], order='id')
        for legacy_price in legacy_prices:
            if not legacy_price.product_id:
                continue
            version = self._find_or_create_legacy_version(legacy_price)
            existing = price_line_model.search([
                ('version_id', '=', version.id),
                ('product_id', '=', legacy_price.product_id.id),
            ], limit=1)
            if existing:
                continue
            price_line_model.create({
                'version_id': version.id,
                'product_id': legacy_price.product_id.id,
                'cash_price': legacy_price.cash_price,
                'list_price': legacy_price.cash_price,
                'note': legacy_price.note or '由 legacy dms.vehicle.price 回填',
            })
