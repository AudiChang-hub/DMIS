from psycopg2 import IntegrityError

from odoo.tests.common import TransactionCase


class TestDmsProductTemplate(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.brand = cls.env['dms.brand'].create({'name': '產品測試品牌 A'})

    def test_01_legacy_product_auto_creates_template_and_code(self):
        product = self.env['dms.product'].create({
            'brand_id': self.brand.id,
            'name': 'JET',
            'model': 'JETSL',
            'year': '2026',
            'color': '曜黑',
            'energy_type': 'oil',
        })
        self.assertTrue(product.template_id, '建立產品項時應自動建立或綁定模板')
        self.assertEqual(product.template_id.family_name, 'JET')
        self.assertEqual(product.template_id.model_name, 'JETSL')
        self.assertEqual(product.production_year, '2026')
        self.assertEqual(product.internal_code, 'JETSL-2026', '應依型號與出廠年份生成可讀 SKU 代碼')

    def test_02_same_template_reused_for_multiple_skus(self):
        product_1 = self.env['dms.product'].create({
            'brand_id': self.brand.id,
            'name': 'MMBCU',
            'model': 'MMB001',
            'year': '2025',
            'color': '藍',
            'energy_type': 'oil',
        })
        product_2 = self.env['dms.product'].create({
            'brand_id': self.brand.id,
            'name': 'MMBCU',
            'model': 'MMB001',
            'year': '2026',
            'color': '灰',
            'energy_type': 'oil',
        })
        self.assertEqual(
            product_1.template_id,
            product_2.template_id,
            '同品牌 / 機種 / 型號的多筆 SKU 應共用同一模板',
        )
        self.assertEqual(product_1.internal_code, 'MMB001-2025')
        self.assertEqual(product_2.internal_code, 'MMB001-2026')

    def test_03_create_product_from_template_syncs_legacy_fields(self):
        template = self.env['dms.product.template'].create({
            'brand_id': self.brand.id,
            'family_name': '測試車系 C',
            'type_name': False,
            'model_name': 'TSTTMPC1',
            'energy_type': 'oil',
        })
        product = self.env['dms.product'].create({
            'template_id': template.id,
            'production_year': '2026',
            'color': '白',
            'active': True,
        })
        self.assertEqual(product.brand_id, self.brand)
        self.assertEqual(product.name, '測試車系 C')
        self.assertEqual(product.model, 'TSTTMPC1')
        self.assertEqual(product.energy_type, 'oil')
        self.assertEqual(product.production_year, '2026')
        self.assertEqual(product.internal_code, 'TSTTMPC1-2026')

    def test_04_internal_code_must_be_unique(self):
        self.env['dms.product'].create({
            'brand_id': self.brand.id,
            'name': 'DRG',
            'model': 'DRG001',
            'year': '2026',
            'color': '黑',
            'energy_type': 'oil',
            'internal_code': 'SKU-UNIQUE-001',
        })

        with self.cr.savepoint(), self.assertRaises(IntegrityError):
            self.env['dms.product'].create({
                'brand_id': self.brand.id,
                'name': 'DRG',
                'model': 'DRG002',
                'year': '2027',
                'color': '白',
                'energy_type': 'oil',
                'internal_code': 'SKU-UNIQUE-001',
            })

    def test_05_generated_internal_code_adds_suffix_on_collision(self):
        product_1 = self.env['dms.product'].create({
            'brand_id': self.brand.id,
            'name': 'FNX',
            'model': 'FNX001',
            'year': '2026',
            'color': '黑',
            'energy_type': 'oil',
        })
        product_2 = self.env['dms.product'].create({
            'brand_id': self.brand.id,
            'name': 'FNX',
            'model': 'FNX001',
            'year': '2026',
            'color': '白',
            'energy_type': 'oil',
        })

        self.assertEqual(product_1.internal_code, 'FNX001-2026')
        self.assertEqual(product_2.internal_code, 'FNX001-2026-02')

    def test_06_production_year_normalizes_comma_format(self):
        product = self.env['dms.product'].create({
            'brand_id': self.brand.id,
            'name': 'MMBCU',
            'model': 'MMB002',
            'year': '2026',
            'production_year': '2,026',
            'color': '白',
            'energy_type': 'oil',
        })

        self.assertEqual(product.production_year, '2026')
        self.assertEqual(product.year, '2026')
        self.assertEqual(product.internal_code, 'MMB002-2026')

    def test_07_template_sku_ids_include_inactive_items(self):
        template = self.env['dms.product.template'].create({
            'brand_id': self.brand.id,
            'family_name': '測試車系 D',
            'type_name': '前碟後鼓',
            'model_name': 'TSTINACT1',
            'energy_type': 'oil',
        })
        active_product = self.env['dms.product'].create({
            'template_id': template.id,
            'production_year': '2026',
            'color': '黑',
            'active': True,
        })
        inactive_product = self.env['dms.product'].create({
            'template_id': template.id,
            'production_year': '2025',
            'color': '紅',
            'active': False,
        })

        template.invalidate_recordset()

        self.assertEqual(template.sku_count, 1)
        self.assertEqual(set(template.sku_ids.ids), {active_product.id, inactive_product.id})
