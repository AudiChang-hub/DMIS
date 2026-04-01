"""
017 — 產品定價簡化測試

TC-01  cash_price/list_price 修改後 price_log 自動寫入
TC-02  promo_price > 0 時 effective_price = promo_price
TC-03  promo_price = 0 時 effective_price = cash_price
TC-04  onchange_product_id 直接讀 product.effective_price
TC-05  onchange_product_id 在 promo_price > 0 時帶入 promo_price
"""
from odoo.tests.common import TransactionCase


class TestProductPricingSimplify(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.brand = cls.env['dms.brand'].create({'name': '017 測試品牌'})
        cls.product = cls.env['dms.product'].create({
            'brand_id': cls.brand.id,
            'name': 'TC017',
            'model': 'TC017-001',
            'year': '2026',
            'color': '白',
            'energy_type': 'oil',
        })

    # ── TC-01 ────────────────────────────────────────────────
    def test_01_cash_price_write_creates_price_log(self):
        """修改 cash_price 後，price_log 被自動寫入"""
        before = len(self.product.price_log_ids)
        self.product.write({'cash_price': 99000})
        after = len(self.product.price_log_ids)
        self.assertEqual(after, before + 1, '應新增一筆 price_log')
        log = self.product.price_log_ids[0]
        self.assertEqual(log.new_cash_price, 99000)
        self.assertEqual(log.old_cash_price, 0)

    # ── TC-02 ────────────────────────────────────────────────
    def test_02_effective_price_uses_promo_when_set(self):
        """promo_price > 0 時，effective_price 回傳 promo_price"""
        self.product.write({'cash_price': 98000, 'promo_price': 95000})
        self.assertEqual(
            self.product.effective_price, 95000,
            'promo_price > 0 時應回傳 promo_price')

    # ── TC-03 ────────────────────────────────────────────────
    def test_03_effective_price_uses_cash_when_no_promo(self):
        """promo_price = 0 時，effective_price 回傳 cash_price"""
        self.product.write({'cash_price': 98000, 'promo_price': 0})
        self.assertEqual(
            self.product.effective_price, 98000,
            'promo_price = 0 時應回傳 cash_price')

    # ── TC-04 ────────────────────────────────────────────────
    def test_04_sale_order_onchange_reads_product_price(self):
        """建立訂單後 onchange 直接讀取 product.effective_price"""
        self.product.write({'cash_price': 89000, 'promo_price': 0})
        order = self.env['dms.sale.order'].new({
            'sale_type': 'store',
            'customer_name': '測試客戶',
        })
        order.product_id = self.product
        order._onchange_product_id()
        self.assertEqual(order.cash_price, 89000,
                         'onchange 應帶入 product.effective_price')

    # ── TC-05 ────────────────────────────────────────────────
    def test_05_sale_order_onchange_uses_promo_price(self):
        """promo_price > 0 時，訂單 onchange 帶入 promo_price 而非 cash_price"""
        self.product.write({'cash_price': 89000, 'promo_price': 86000})
        order = self.env['dms.sale.order'].new({
            'sale_type': 'store',
            'customer_name': '測試客戶',
        })
        order.product_id = self.product
        order._onchange_product_id()
        self.assertEqual(order.cash_price, 86000,
                         'promo_price > 0 時 onchange 應帶入 promo_price')

    # ── TC-06 ────────────────────────────────────────────────
    def test_06_installment_rule_m2m(self):
        """可在 product 上加入/移除分期規則"""
        rule = self.env['dms.installment.rule'].create({'name': 'TC017 分期規則'})
        self.product.write({'installment_rule_ids': [(4, rule.id)]})
        self.assertIn(rule, self.product.installment_rule_ids,
                      '分期規則應成功掛接到產品')
        self.product.write({'installment_rule_ids': [(3, rule.id)]})
        self.assertNotIn(rule, self.product.installment_rule_ids,
                         '分期規則應成功從產品移除')
