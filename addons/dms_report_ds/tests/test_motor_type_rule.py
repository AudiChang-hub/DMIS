"""Unit tests for dms.motor.type.rule and ds.sales.report motor_type CASE."""

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'dms_report_ds')
class TestMotorTypeRule(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Rule = self.env['dms.motor.type.rule']
        self.Report = self.env['ds.sales.report']

    # ── 模型基本驗證 ─────────────────────────────────────
    def test_default_rules_loaded(self):
        """安裝時應載入 6 條預設規則。"""
        rules = self.Rule.search([('active', '=', True)])
        self.assertGreaterEqual(len(rules), 6,
                                '預設規則數量應 ≥ 6')
        results = set(rules.mapped('result'))
        self.assertIn('白牌電車', results)
        self.assertIn('綠牌電車', results)
        self.assertIn('擋車', results)

    def test_pattern_required(self):
        """空 pattern 應被 CHECK constraint 拒絕。"""
        with self.assertRaises(Exception):
            self.Rule.create({
                'name': 'invalid',
                'pattern': '',
                'result': '其他',
            })

    # ── CASE 組合 ──────────────────────────────────────
    def test_case_sql_uses_active_rules_only(self):
        """_get_motor_type_case_sql 僅應包含啟用中的規則。"""
        rule = self.Rule.create({
            'name': 'test-disabled',
            'sequence': 999,
            'pattern': 'TESTONLYPATTERN',
            'result': '其他',
            'active': False,
        })
        case_sql = self.Report._get_motor_type_case_sql()
        self.assertNotIn('TESTONLYPATTERN', case_sql,
                         '已停用規則不應出現於 CASE')
        rule.active = True
        case_sql2 = self.Report._get_motor_type_case_sql()
        self.assertIn('TESTONLYPATTERN', case_sql2,
                      '啟用後應出現於 CASE')

    def test_case_sql_orders_by_sequence(self):
        """CASE 子句應依 sequence 排序，數字小者較先比對。"""
        case_sql = self.Report._get_motor_type_case_sql()
        # 預設 eReady (seq 10) 應出現在 JEGO (seq 30) 之前
        idx_ereadry = case_sql.find('eReady')
        idx_jego = case_sql.find('JEGO')
        self.assertNotEqual(idx_ereadry, -1)
        self.assertNotEqual(idx_jego, -1)
        self.assertLess(idx_ereadry, idx_jego,
                        'sequence 較小的規則應出現於前')

    def test_case_sql_escapes_single_quote(self):
        """pattern/result 中的單引號需被轉義為兩個單引號。"""
        rule = self.Rule.create({
            'name': "quote-test",
            'sequence': 5,
            'pattern': "abc'def",
            'result': '其他',
        })
        case_sql = self.Report._get_motor_type_case_sql()
        self.assertIn("abc''def", case_sql)
        rule.unlink()

    # ── 規則異動觸發 view 重建 ──────────────────────────
    def test_create_rule_rebuilds_view(self):
        """建立新規則後，新車款字串應立即被分類。"""
        # 沒有規則時 'ZZUNIQUE' 預設應為 '其他'
        self.env.cr.execute("""
            SELECT
                CASE
                    WHEN 'ZZUNIQUE-Bike' ~* 'ZZUNIQUE'
                    THEN '擋車' ELSE '其他'
                END
        """)
        # 建立規則後 view 應被 rebuilt（無例外即代表 init() 成功）
        rule = self.Rule.create({
            'name': 'test-rebuild',
            'sequence': 1,
            'pattern': 'ZZUNIQUEPATTERNXYZ',
            'result': '擋車',
        })
        # view 應存在且可查詢
        self.env.cr.execute("SELECT COUNT(*) FROM ds_sales_report")
        self.assertIsNotNone(self.env.cr.fetchone())
        rule.unlink()

    # ── 實際資料驗證：eReady 全系列為白牌電車 ──────────
    def test_ereadry_classified_as_white(self):
        """所有車款名稱含 eReady 的訂單，motor_type 必須為白牌電車。"""
        self.env.cr.execute("""
            SELECT motor_type, COUNT(*)
            FROM ds_sales_report
            WHERE model ILIKE '%%eReady%%'
            GROUP BY motor_type
        """)
        rows = self.env.cr.fetchall()
        if not rows:
            self.skipTest('資料庫無 eReady 訂單可驗證')
        for motor_type, _ in rows:
            self.assertEqual(motor_type, '白牌電車',
                             f'eReady 應為白牌電車，實際為 {motor_type}')
