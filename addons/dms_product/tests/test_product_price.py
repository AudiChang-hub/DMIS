from datetime import date

from odoo.tests.common import TransactionCase


class TestDmsProductPrice(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.brand = cls.env['dms.brand'].create({'name': '產品測試品牌 B'})
        cls.product = cls.env['dms.product'].create({
            'brand_id': cls.brand.id,
            'name': 'CLBCU',
            'model': 'CLB001',
            'year': '2025',
            'color': '銀',
            'energy_type': 'oil',
        })

    def test_01_effective_price_line_lookup(self):
        version_jan = self.env['dms.price.version'].create({
            'name': '2026-01',
            'effective_date': date(2026, 1, 1),
            'state': 'effective',
        })
        version_mar = self.env['dms.price.version'].create({
            'name': '2026-03',
            'effective_date': date(2026, 3, 1),
            'state': 'effective',
        })
        line_jan = self.env['dms.price.line'].create({
            'version_id': version_jan.id,
            'product_id': self.product.id,
            'cash_price': 82000,
            'list_price': 86000,
        })
        line_mar = self.env['dms.price.line'].create({
            'version_id': version_mar.id,
            'product_id': self.product.id,
            'cash_price': 83000,
            'list_price': 87000,
        })

        effective_feb = self.env['dms.price.line'].get_effective_line(
            self.product, query_date=date(2026, 2, 15))
        effective_apr = self.env['dms.price.line'].get_effective_line(
            self.product, query_date=date(2026, 4, 1))

        self.assertEqual(effective_feb, line_jan)
        self.assertEqual(effective_apr, line_mar)

    def test_02_sale_order_onchange_prefers_new_price_line(self):
        self.env['dms.price.version'].create({
            'name': '2026-05',
            'effective_date': date(2026, 5, 1),
            'state': 'effective',
            'line_ids': [(0, 0, {
                'product_id': self.product.id,
                'cash_price': 84500,
                'list_price': 88500,
            })],
        })
        self.env['dms.vehicle.price'].create({
            'product_id': self.product.id,
            'cash_price': 79999,
            'valid_year_month': '2026-05',
            'active': True,
        })

        order = self.env['dms.sale.order'].new({
            'customer_name': '測試客戶',
            'product_id': self.product.id,
            'order_date': date(2026, 5, 10),
        })
        order._onchange_product_id()

        self.assertEqual(order.cash_price, 84500, '查價應優先讀取新價格結構')

    def test_03_sale_order_price_fallback_to_legacy_vehicle_price(self):
        product = self.env['dms.product'].create({
            'brand_id': self.brand.id,
            'name': 'DRG',
            'model': 'DRG001',
            'year': '2025',
            'color': '紅',
            'energy_type': 'oil',
        })
        self.env['dms.vehicle.price'].create({
            'product_id': product.id,
            'cash_price': 90500,
            'valid_year_month': '2026-06',
            'active': True,
        })

        order = self.env['dms.sale.order'].new({
            'customer_name': '測試客戶',
            'product_id': product.id,
            'order_date': date(2026, 6, 10),
        })
        order._onchange_product_id()

        self.assertEqual(order.cash_price, 90500, '新價格不存在時，應 fallback 舊價格結構')

    def test_04_product_name_get_includes_year_and_color(self):
        label = self.product.display_name

        self.assertIn(self.product.internal_code, label)
        self.assertIn('2025', label)
        self.assertIn('銀', label)

    def test_05_bulk_add_wizard_creates_multiple_price_lines(self):
        product_2 = self.env['dms.product'].create({
            'brand_id': self.brand.id,
            'name': 'CLBCU',
            'model': 'CLB001',
            'year': '2026',
            'color': '黑',
            'energy_type': 'oil',
        })
        version = self.env['dms.price.version'].create({
            'name': '2026-07',
            'effective_date': date(2026, 7, 1),
            'state': 'draft',
        })

        wizard = self.env['dms.price.version.bulk.add.wizard'].create({
            'version_id': version.id,
            'product_ids': [(6, 0, [self.product.id, product_2.id])],
        })
        action = wizard.action_add_lines()
        lines = self.env['dms.price.line'].search([('version_id', '=', version.id)])

        self.assertEqual(len(lines), 2)
        self.assertEqual(set(lines.mapped('product_id').ids), {self.product.id, product_2.id})
        self.assertEqual(set(lines.mapped('cash_price')), {0})
        self.assertEqual(set(lines.mapped('list_price')), {0})
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'reload')
