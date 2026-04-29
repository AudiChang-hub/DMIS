"""Unit tests for dms.dealer.brand.rule and refactored channel/brand SQL."""

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'dms_report_ds')
class TestDealerBrandRule(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Rule = self.env['dms.dealer.brand.rule']
        self.Report = self.env['ds.sales.report']

    def test_default_rules_loaded(self):
        rules = self.Rule.search([('active', '=', True)])
        results = set(rules.mapped('result'))
        self.assertGreaterEqual(len(rules), 8)
        for brand in ('光陽', '三陽', '山葉', '台鈴', '睿能', '一般車行'):
            self.assertIn(brand, results,
                          f'預設規則應包含 {brand}')

    def test_brand_case_includes_prefix_clauses(self):
        case_sql = self.Report._get_brand_type_case_sql()
        self.assertIn("s.dname = ''", case_sql)
        self.assertIn("'馭盛網推'", case_sql)
        self.assertIn("s.store_type_name = '網路平台'", case_sql)
        self.assertIn("s.dname ~ '中古車'", case_sql)
        self.assertTrue(case_sql.rstrip().endswith("ELSE s.dname\n                END"))

    def test_brand_case_orders_by_sequence(self):
        case_sql = self.Report._get_brand_type_case_sql()
        idx_kymco = case_sql.find('鑫輝')   # seq 10
        idx_yamaha = case_sql.find('馳機')   # seq 30
        self.assertNotEqual(idx_kymco, -1)
        self.assertNotEqual(idx_yamaha, -1)
        self.assertLess(idx_kymco, idx_yamaha)

    def test_brand_rule_rebuild_on_create(self):
        self.Rule.create({
            'name': 'test-temp-brand',
            'sequence': 999,
            'pattern': 'ZZTESTBRAND',
            'result': '測試品牌',
        })
        case_sql = self.Report._get_brand_type_case_sql()
        self.assertIn('ZZTESTBRAND', case_sql)
        self.env.cr.execute("SELECT COUNT(*) FROM ds_sales_report")
        self.assertIsNotNone(self.env.cr.fetchone())

    def test_pattern_required(self):
        with self.assertRaises(Exception):
            self.Rule.create({
                'name': 'invalid',
                'pattern': '',
                'result': '光陽',
            })

    def test_result_required(self):
        with self.assertRaises(Exception):
            self.Rule.create({
                'name': 'invalid2',
                'pattern': 'foo',
                'result': '',
            })

    # ── 整合驗證：JOIN store_type 後網路平台分類 ─────────
    def test_online_dealers_classified_as_online(self):
        """store_type='網路平台' 的車行訂單，sales_type 與 brand_type 應為 '網路平台'。"""
        self.env.cr.execute("""
            SELECT COUNT(*) FROM ds_sales_report r
            JOIN dms_sale_order so ON so.id = r.id
            JOIN dms_dealer d ON d.id = so.dealer_id
            JOIN dms_store_type st ON st.id = d.store_type_id
            WHERE st.name = '網路平台'
              AND (r.sales_type::text != '網路平台'
                   OR r.brand_type != '網路平台')
        """)
        bad = self.env.cr.fetchone()[0]
        self.assertEqual(bad, 0,
                         '網路平台車行訂單必須全部歸為網路平台')
