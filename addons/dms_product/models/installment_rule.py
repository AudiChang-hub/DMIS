from odoo import api, fields, models


class DmsInstallmentRule(models.Model):
    _name = 'dms.installment.rule'
    _description = '分期規則模板'
    _order = 'name, id'

    name = fields.Char(string='規則名稱', required=True)
    active = fields.Boolean(string='啟用', default=True)
    interest_rate = fields.Float(
        string='年利率', digits=(5, 4), default=0.0,
        help='年利率（小數），例：0.0 表示 0%，0.05 表示 5%。無利率方案填 0 即可。')
    note = fields.Text(string='備註')
    line_ids = fields.One2many(
        'dms.installment.rule.line', 'rule_id', string='規則明細')
    binding_ids = fields.One2many(
        'dms.installment.rule.binding', 'rule_id', string='規則掛接')

    _sql_constraints = [
        ('unique_installment_rule_name', 'unique(name)', '分期規則名稱不可重複。'),
    ]

    @api.model
    def _run_legacy_backfill(self):
        if 'dms.installment.plan' not in self.env.registry.models:
            return
        version_model = self.env['dms.price.version']
        price_line_model = self.env['dms.price.line']
        binding_model = self.env['dms.installment.rule.binding']
        line_model = self.env['dms.installment.rule.line']

        legacy_plans = self.env['dms.installment.plan'].search([], order='id')
        for legacy_plan in legacy_plans:
            legacy_price = legacy_plan.price_id
            if not legacy_price or not legacy_price.product_id:
                continue

            version = version_model._find_or_create_legacy_version(legacy_price)
            price_line = price_line_model.search([
                ('version_id', '=', version.id),
                ('product_id', '=', legacy_price.product_id.id),
            ], limit=1)
            if not price_line:
                price_line = price_line_model.create({
                    'version_id': version.id,
                    'product_id': legacy_price.product_id.id,
                    'cash_price': legacy_price.cash_price,
                    'list_price': legacy_price.cash_price,
                    'note': legacy_price.note or '由 legacy dms.vehicle.price 回填',
                })

            rule_name = (
                f"Legacy {legacy_price.product_id.display_name} "
                f"{legacy_price.valid_year_month or 'default'}"
            )
            rule = self.search([('name', '=', rule_name)], limit=1)
            if not rule:
                rule = self.create({
                    'name': rule_name,
                    'active': legacy_plan.active,
                    'note': '由 legacy dms.installment.plan 自動回填',
                })

            existing_line = line_model.search([
                ('rule_id', '=', rule.id),
                ('period_from', '=', legacy_plan.installment_periods),
                ('period_to', '=', legacy_plan.installment_periods),
            ], limit=1)
            if not existing_line:
                line_model.create({
                    'rule_id': rule.id,
                    'period_from': legacy_plan.installment_periods,
                    'period_to': legacy_plan.installment_periods,
                    'price_basis': 'cash',
                    'note': legacy_plan.finance_company or '由 legacy installment plan 回填',
                })

            existing_binding = binding_model.search([
                ('product_id', '=', legacy_price.product_id.id),
                ('price_version_id', '=', version.id),
            ], limit=1)
            if not existing_binding:
                binding_model.create({
                    'product_id': legacy_price.product_id.id,
                    'price_version_id': version.id,
                    'rule_id': rule.id,
                    'active': legacy_plan.active,
                    'note': '由 legacy installment plan 自動建立',
                })
