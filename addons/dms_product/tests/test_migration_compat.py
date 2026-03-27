from odoo.tests.common import TransactionCase


class TestDmsProductMigrationCompat(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.brand = cls.env['dms.brand'].create({'name': '產品測試品牌 D'})

    def test_01_run_product_backfill_for_legacy_records(self):
        legacy_product = self.env['dms.product'].with_context(
            skip_product_compat_sync=True
        ).create({
            'brand_id': self.brand.id,
            'name': '測試車系 A',
            'model': 'TSTMIGA1',
            'year': '2026',
            'color': '鈦灰',
            'energy_type': 'oil',
        })
        self.assertFalse(legacy_product.template_id)
        self.assertFalse(legacy_product.internal_code)

        self.env['dms.product']._run_product_backfill()
        legacy_product.invalidate_recordset()

        self.assertTrue(legacy_product.template_id)
        self.assertEqual(legacy_product.production_year, 2026)
        self.assertEqual(legacy_product.internal_code, 'TSTMIGA1-2026')

    def test_02_run_product_backfill_rewrites_legacy_generated_code(self):
        legacy_product = self.env['dms.product'].with_context(
            skip_product_compat_sync=True
        ).create({
            'brand_id': self.brand.id,
            'name': '測試車系 B',
            'model': 'TSTMIGB1',
            'year': '2026',
            'color': '白',
            'energy_type': 'oil',
            'internal_code': 'SKU-00001',
        })

        self.env['dms.product']._run_product_backfill()
        legacy_product.invalidate_recordset()

        self.assertEqual(legacy_product.internal_code, 'TSTMIGB1-2026')

    def test_03_run_price_and_rule_backfill_for_legacy_models(self):
        product = self.env['dms.product'].create({
            'brand_id': self.brand.id,
            'name': 'Saluto',
            'model': 'UC125DA',
            'year': '2026',
            'color': '紅',
            'energy_type': 'oil',
        })
        legacy_price = self.env['dms.vehicle.price'].create({
            'product_id': product.id,
            'cash_price': 73500,
            'valid_year_month': '2026-08',
            'active': True,
        })
        self.env['dms.installment.plan'].create({
            'price_id': legacy_price.id,
            'installment_periods': 24,
            'installment_monthly': 3200,
            'finance_company': '測試分期公司',
            'active': True,
        })

        self.env['dms.price.version']._run_legacy_backfill()
        self.env['dms.installment.rule']._run_legacy_backfill()

        version = self.env['dms.price.version'].search([('name', '=', 'Legacy 2026-08')], limit=1)
        price_line = self.env['dms.price.line'].search([
            ('version_id', '=', version.id),
            ('product_id', '=', product.id),
        ], limit=1)
        binding = self.env['dms.installment.rule.binding'].search([
            ('product_id', '=', product.id),
            ('price_version_id', '=', version.id),
        ], limit=1)

        self.assertTrue(version, '應回填 legacy 價目版本')
        self.assertTrue(price_line, '應回填 legacy 價格基準')
        self.assertEqual(price_line.cash_price, 73500)
        self.assertTrue(binding, '應建立 legacy 規則掛接')
        self.assertTrue(binding.rule_id.line_ids, '應建立至少一筆規則明細')
