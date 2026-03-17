"""
dms_report_rule 單元測試

TC-01  建立規則，驗證欄位預設值（owner, active, public, chart_type）
TC-02  預覽報表 — pivot 模式回傳正確 action dict
TC-03  預覽報表 — bar graph 模式回傳正確 action dict，含 graph_type
TC-04  非法 filter_domain → 視為空 domain，不拋出例外
TC-05  record rule — 使用者（非 admin）無法讀取他人私有規則
TC-06  record rule — 使用者可讀取他人公開規則
"""
from odoo.tests.common import TransactionCase
from odoo.exceptions import AccessError


class TestReportRule(TransactionCase):

    def setUp(self):
        super().setUp()
        # 取得 dms.sale.order 的 ir.model 記錄
        self.ir_model_sale = self.env['ir.model'].search(
            [('model', '=', 'dms.sale.order')], limit=1)

        # 取得可作為維度的欄位（date/datetime/many2one）
        self.dim_field = self.env['ir.model.fields'].search([
            ('model_id', '=', self.ir_model_sale.id),
            ('ttype', 'in', ['date', 'datetime', 'many2one']),
        ], limit=1)

        # 取得可作為指標的欄位（float/integer/monetary）
        self.measure_field = self.env['ir.model.fields'].search([
            ('model_id', '=', self.ir_model_sale.id),
            ('ttype', 'in', ['float', 'integer', 'monetary']),
        ], limit=1)

    # ── TC-01 ────────────────────────────────────────────────
    def test_01_create_defaults(self):
        """建立規則後，owner=當前使用者，active=True，public=False，chart_type=bar"""
        rule = self.env['dms.report.rule'].create({
            'name': '測試規則 TC01',
            'model_id': self.ir_model_sale.id,
            'chart_type': 'bar',
        })
        self.assertEqual(rule.owner_id, self.env.user,
                         'owner_id 應預設為當前使用者')
        self.assertTrue(rule.active, 'active 應預設為 True')
        self.assertFalse(rule.public, 'public 應預設為 False')
        self.assertEqual(rule.chart_type, 'bar', 'chart_type 應為 bar')

    # ── TC-02 ────────────────────────────────────────────────
    def test_02_preview_pivot(self):
        """pivot 模式：view_mode 為 pivot,tree；context 含 group_by"""
        rule = self.env['dms.report.rule'].create({
            'name': '樞紐分析規則',
            'model_id': self.ir_model_sale.id,
            'chart_type': 'pivot',
            'dimension_ids': [(6, 0, self.dim_field.ids)],
            'measure_ids': [(6, 0, self.measure_field.ids)],
        })
        action = rule.action_preview_report()
        self.assertEqual(action.get('type'), 'ir.actions.act_window')
        self.assertEqual(action.get('res_model'), 'dms.sale.order')
        self.assertIn('pivot', action.get('view_mode', ''))
        ctx = action.get('context', {})
        self.assertIn('group_by', ctx, '應有 group_by')
        self.assertIn('pivot_measures', ctx, '應有 pivot_measures')
        self.assertNotIn('graph_type', ctx, 'pivot 模式不應有 graph_type')

    # ── TC-03 ────────────────────────────────────────────────
    def test_03_preview_bar_graph(self):
        """bar 模式：view_mode 包含 graph；context 含 graph_type=bar"""
        rule = self.env['dms.report.rule'].create({
            'name': 'Bar 圖規則',
            'model_id': self.ir_model_sale.id,
            'chart_type': 'bar',
            'dimension_ids': [(6, 0, self.dim_field.ids)],
        })
        action = rule.action_preview_report()
        self.assertEqual(action.get('type'), 'ir.actions.act_window')
        self.assertIn('graph', action.get('view_mode', ''))
        ctx = action.get('context', {})
        self.assertEqual(ctx.get('graph_type'), 'bar')

    # ── TC-04 ────────────────────────────────────────────────
    def test_04_invalid_filter_domain(self):
        """非法 filter_domain 不應拋出例外，domain 應為空列表"""
        rule = self.env['dms.report.rule'].create({
            'name': '非法 domain 測試',
            'model_id': self.ir_model_sale.id,
            'chart_type': 'bar',
            'filter_domain': 'THIS IS NOT A DOMAIN',
        })
        try:
            action = rule.action_preview_report()
        except Exception as e:
            self.fail(f'action_preview_report 不應拋出例外：{e}')
        self.assertEqual(action.get('domain'), [],
                         '非法 domain 應回傳空列表')

    # ── TC-05 ────────────────────────────────────────────────
    def test_05_record_rule_private_not_visible(self):
        """
        使用者 A 建立的私有規則（public=False），
        以 sudo 變換至另一使用者後不應能在 search 中看到。
        """
        # 建立 owner_id = admin 的私有規則
        rule = self.env['dms.report.rule'].sudo().create({
            'name': '私有規則 TC05',
            'model_id': self.ir_model_sale.id,
            'chart_type': 'bar',
            'public': False,
            'owner_id': self.env.ref('base.user_admin').id,
        })

        # 建立一個一般測試使用者（無 admin 權限）
        test_user = self.env['res.users'].sudo().create({
            'name': '測試非管理員',
            'login': 'test_non_admin_rr',
            'groups_id': [(6, 0, [
                self.env.ref('dms_report_rule.group_dms_report_rule_user').id,
            ])],
        })

        # 以測試使用者的身份搜尋規則
        visible_rules = self.env['dms.report.rule'].with_user(test_user).search(
            [('id', '=', rule.id)])
        self.assertFalse(visible_rules,
                         '私有規則不應對非 owner 的使用者可見')

    # ── TC-06 ────────────────────────────────────────────────
    def test_06_record_rule_public_visible(self):
        """
        使用者 A 建立的公開規則（public=True），
        其他使用者應可在 search 中看到。
        """
        rule = self.env['dms.report.rule'].sudo().create({
            'name': '公開規則 TC06',
            'model_id': self.ir_model_sale.id,
            'chart_type': 'bar',
            'public': True,
            'owner_id': self.env.ref('base.user_admin').id,
        })

        test_user = self.env['res.users'].sudo().create({
            'name': '測試非管理員 2',
            'login': 'test_non_admin_rr2',
            'groups_id': [(6, 0, [
                self.env.ref('dms_report_rule.group_dms_report_rule_user').id,
            ])],
        })

        visible_rules = self.env['dms.report.rule'].with_user(test_user).search(
            [('id', '=', rule.id)])
        self.assertTrue(visible_rules,
                        '公開規則應對所有使用者可見')
