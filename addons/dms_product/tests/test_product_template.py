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
        self.assertEqual(product.production_year, 2026)
        self.assertTrue(product.internal_code, '應自動生成內部唯一代碼')

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

    def test_03_create_product_from_template_syncs_legacy_fields(self):
        template = self.env['dms.product.template'].create({
            'brand_id': self.brand.id,
            'family_name': 'Saluto',
            'type_name': False,
            'model_name': 'UC125DA',
            'energy_type': 'oil',
        })
        product = self.env['dms.product'].create({
            'template_id': template.id,
            'production_year': 2026,
            'color': '白',
            'active': True,
        })
        self.assertEqual(product.brand_id, self.brand)
        self.assertEqual(product.name, 'Saluto')
        self.assertEqual(product.model, 'UC125DA')
        self.assertEqual(product.energy_type, 'oil')

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
