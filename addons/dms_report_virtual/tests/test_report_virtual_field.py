"""
dms_report_virtual 單元測試

測試對象：dms.report.virtual.field + dms.report.virtual.field.rule
測試資料：使用 res.partner（永遠可用，不須依賴 DMS 模組資料）

TC-01  建立虛擬欄位，驗證預設值（active, public, owner, rule_count）
TC-02  contains 規則匹配成功 → 返回正確輸出值
TC-03  regex 規則匹配（'|' 多關鍵字）→ 返回正確輸出值
TC-04  python 規則返回自訂值（表達式直接作為輸出）
TC-05  所有規則未匹配 → 返回 default_value
TC-06  action_preview_report 含虛擬維度 → 回傳精靈 action dict
TC-07  Record Rule：使用者不可讀取他人私有虛擬欄位
TC-08  非法 regex 儲存時應觸發 ValidationError
"""
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestReportVirtualField(TransactionCase):

    def setUp(self):
        super().setUp()
        # 使用 res.partner 作為作用模型（無需依賴 DMS 資料）
        self.ir_model_partner = self.env['ir.model'].search(
            [('model', '=', 'res.partner')], limit=1)

        # 建立測試用 partner
        self.partner = self.env['res.partner'].create({
            'name': 'Yamaha 敦南機車',
            'email': 'test@yamaha.example.com',
        })

    def _make_vf(self, **kwargs):
        """建立虛擬欄位的便利方法。"""
        defaults = {
            'name': '測試虛擬欄位',
            'code': 'test_vf_%d' % id(self),
            'model_id': self.ir_model_partner.id,
            'compute_type': 'rule',
        }
        defaults.update(kwargs)
        return self.env['dms.report.virtual.field'].create(defaults)

    def _make_rule(self, vf, **kwargs):
        """建立規則的便利方法。"""
        defaults = {
            'virtual_field_id': vf.id,
            'sequence': 10,
            'match_type': 'contains',
            'field_name': 'name',
            'condition': 'Yamaha',
            'value': '山葉品牌',
        }
        defaults.update(kwargs)
        return self.env['dms.report.virtual.field.rule'].create(defaults)

    # ── TC-01 ────────────────────────────────────────────────
    def test_01_create_defaults(self):
        """建立虛擬欄位後，owner=當前使用者，active=True，public=False"""
        vf = self._make_vf(code='tc01_vf')
        self.assertEqual(vf.owner_id, self.env.user, 'owner_id 應預設為當前使用者')
        self.assertTrue(vf.active, 'active 應預設為 True')
        self.assertFalse(vf.public, 'public 應預設為 False')
        self.assertEqual(vf.rule_count, 0, '初始時規則數應為 0')

    # ── TC-02 ────────────────────────────────────────────────
    def test_02_contains_rule_match(self):
        """contains 規則：name 包含 Yamaha → 輸出「山葉品牌」"""
        vf = self._make_vf(code='tc02_vf')
        self._make_rule(vf, condition='Yamaha', value='山葉品牌')

        result = vf.compute_value(self.partner)
        self.assertEqual(result, '山葉品牌', 'contains 規則應匹配並返回「山葉品牌」')

    # ── TC-03 ────────────────────────────────────────────────
    def test_03_regex_rule_match(self):
        """regex 規則：name 匹配 'Yamaha|山葉' → 輸出「山葉品牌」"""
        vf = self._make_vf(code='tc03_vf')
        self._make_rule(vf,
                        match_type='regex',
                        condition=r'Yamaha|山葉',
                        value='山葉品牌')

        result = vf.compute_value(self.partner)
        self.assertEqual(result, '山葉品牌', 'regex 規則應匹配「Yamaha 敦南機車」中的 Yamaha')

    # ── TC-04 ────────────────────────────────────────────────
    def test_04_python_rule_custom_value(self):
        """python 規則：表達式直接返回值「山葉」"""
        vf = self._make_vf(code='tc04_vf')
        self._make_rule(vf,
                        match_type='python',
                        field_name='',
                        condition='',
                        python_expression="'Yamaha' in record.name and '山葉' or False",
                        value='（不用此值）')

        result = vf.compute_value(self.partner)
        self.assertEqual(result, '山葉', 'python 規則表達式返回的值應直接作為輸出')

    # ── TC-05 ────────────────────────────────────────────────
    def test_05_no_match_returns_default(self):
        """所有規則未匹配時，返回 default_value"""
        vf = self._make_vf(code='tc05_vf', default_value='其他品牌')
        self._make_rule(vf, condition='Honda', value='本田品牌')

        result = vf.compute_value(self.partner)
        self.assertEqual(result, '其他品牌',
                         '無規則匹配時應返回 default_value「其他品牌」')

    # ── TC-06 ────────────────────────────────────────────────
    def test_06_action_preview_with_virtual(self):
        """
        dms.report.rule + virtual_dimension_ids → action_preview_report
        應回傳 dms.report.vf.preview 的精靈 action（target=new）。
        """
        # 取得 ir.model for res.partner (as test model)
        ir_model = self.ir_model_partner

        # 建立虛擬欄位
        vf = self._make_vf(code='tc06_vf', public=True)
        self._make_rule(vf, condition='Yamaha', value='山葉品牌')

        # 建立報表規則
        rule = self.env['dms.report.rule'].create({
            'name': 'TC06 報表規則',
            'model_id': ir_model.id,
            'chart_type': 'bar',
            'virtual_dimension_ids': [(6, 0, [vf.id])],
        })

        action = rule.action_preview_report()

        self.assertEqual(action.get('type'), 'ir.actions.act_window',
                         'action type 應為 ir.actions.act_window')
        self.assertEqual(action.get('res_model'), 'dms.report.vf.preview',
                         '有虛擬維度時應開啟預覽精靈')
        self.assertEqual(action.get('target'), 'new',
                         'target 應為 new（精靈視窗）')

        # 確認精靈記錄已建立並有分組行
        preview_id = action.get('res_id')
        self.assertTrue(preview_id, '應有 res_id 指向精靈記錄')
        preview = self.env['dms.report.vf.preview'].browse(preview_id)
        self.assertTrue(preview.exists(), '精靈記錄應存在')

    # ── TC-07 ────────────────────────────────────────────────
    def test_07_record_rule_private_not_visible(self):
        """Record Rule：使用者無法讀取他人私有（public=False）的虛擬欄位"""
        # admin 建立一個私有虛擬欄位
        vf = self.env['dms.report.virtual.field'].sudo().create({
            'name': '私有虛擬欄位 TC07',
            'code': 'tc07_private_vf',
            'model_id': self.ir_model_partner.id,
            'compute_type': 'rule',
            'public': False,
            'owner_id': self.env.ref('base.user_admin').id,
        })

        # 建立一般使用者（只有 virtual user group）
        test_user = self.env['res.users'].sudo().create({
            'name': '測試一般使用者 TC07',
            'login': 'test_vf_user_tc07',
            'groups_id': [(6, 0, [
                self.env.ref(
                    'dms_report_virtual.group_dms_report_virtual_user').id,
            ])],
        })

        visible = self.env['dms.report.virtual.field'].with_user(test_user).search(
            [('id', '=', vf.id)])
        self.assertFalse(visible,
                         '私有虛擬欄位不應對非 owner 的使用者可見')

    # ── TC-08 ────────────────────────────────────────────────
    def test_08_invalid_regex_raises_error(self):
        """儲存含非法 regex 的規則時應觸發 ValidationError"""
        vf = self._make_vf(code='tc08_vf')
        with self.assertRaises(ValidationError):
            self.env['dms.report.virtual.field.rule'].create({
                'virtual_field_id': vf.id,
                'sequence': 10,
                'match_type': 'regex',
                'field_name': 'name',
                'condition': '[invalid_regex',  # 非法正則
                'value': '輸出值',
            })
