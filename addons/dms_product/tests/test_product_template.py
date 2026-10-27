from psycopg2 import IntegrityError

from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


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
        self.assertEqual(product.internal_code, 'JETSL-2026', '應依型號與出廠年份生成可讀產品項代碼')
        self.assertEqual(len(product.color_ids), 1)
        self.assertEqual(product.color_ids.name, '曜黑')
        self.assertEqual(product.color, '曜黑')

    def test_02_same_template_reused_for_multiple_year_items(self):
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
            '同品牌 / 機種 / 型號的多筆產品項應共用同一模板',
        )
        self.assertEqual(product_1.internal_code, 'MMB001-2025')
        self.assertEqual(product_2.internal_code, 'MMB001-2026')
        self.assertEqual(product_1.color_ids.name, '藍')
        self.assertEqual(product_2.color_ids.name, '灰')

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
        self.assertEqual(product.color_ids.name, '白')

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

    def test_05_same_template_and_year_should_not_duplicate_by_color(self):
        product_1 = self.env['dms.product'].create({
            'brand_id': self.brand.id,
            'name': 'FNX',
            'model': 'FNX001',
            'year': '2026',
            'color': '黑',
            'energy_type': 'oil',
        })

        with self.cr.savepoint(), self.assertRaises(ValidationError):
            self.env['dms.product'].create({
                'brand_id': self.brand.id,
                'name': 'FNX',
                'model': 'FNX001',
                'year': '2026',
                'color': '白',
                'energy_type': 'oil',
            })

        self.assertEqual(product_1.internal_code, 'FNX001-2026')
        self.assertEqual(product_1.color_ids.name, '黑')

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
        self.assertEqual(product.color_ids.name, '白')

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
        self.assertEqual(set(template.product_color_ids.mapped('name')), {'黑', '紅'})

    def test_08_template_copy_creates_new_template_with_skus(self):
        template = self.env['dms.product.template'].create({
            'brand_id': self.brand.id,
            'family_name': '測試車系 E',
            'type_name': '前碟後鼓',
            'model_name': 'TSTCOPY1',
            'energy_type': 'oil',
        })
        self.env['dms.product'].create({
            'template_id': template.id,
            'production_year': '2026',
            'color': '黑',
            'active': True,
        })

        copied_template = template.copy()

        self.assertNotEqual(copied_template.id, template.id)
        self.assertEqual(copied_template.brand_id, template.brand_id)
        self.assertEqual(copied_template.family_name, template.family_name)
        self.assertEqual(copied_template.model_name, template.model_name)
        self.assertEqual(len(copied_template.sku_ids), 1)
        self.assertNotEqual(copied_template.sku_ids.internal_code, template.sku_ids.internal_code)
        self.assertEqual(copied_template.sku_ids.color_ids.name, '黑')

    def test_09_template_can_delete_unreferenced_sku_from_tab(self):
        template = self.env['dms.product.template'].create({
            'brand_id': self.brand.id,
            'family_name': '測試車系 F',
            'type_name': '雙碟',
            'model_name': 'TSTDEL1',
            'energy_type': 'oil',
        })
        sku = self.env['dms.product'].create({
            'template_id': template.id,
            'production_year': '2026',
            'color': '藍',
            'active': True,
        })

        template.write({'sku_ids': [(2, sku.id, 0)]})

        self.assertFalse(self.env['dms.product'].with_context(active_test=False).browse(sku.id).exists())

    def test_10_template_tab_can_duplicate_sku(self):
        template = self.env['dms.product.template'].create({
            'brand_id': self.brand.id,
            'family_name': '測試車系 G',
            'type_name': '雙碟',
            'model_name': 'TSTDUP1',
            'energy_type': 'oil',
        })
        sku = self.env['dms.product'].create({
            'template_id': template.id,
            'production_year': '2026',
            'color': '鈦灰',
            'active': True,
        })

        # 複製按鈕現在開啟 wizard，由 wizard 負責填年份後才真正 copy()
        action = sku.action_duplicate_from_template_tab()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['target'], 'new')
        self.assertEqual(action['res_model'], 'dms.product.duplicate.wizard')

        # 驗證 wizard 邏輯：無衝突時直接建立並開啟 product form
        wizard = self.env['dms.product.duplicate.wizard'].browse(action['res_id'])
        self.assertEqual(wizard.source_product_id, sku)
        wizard.write({'production_year': '2027'})
        result = wizard.action_check_and_create()
        self.assertEqual(result['type'], 'ir.actions.act_window')
        self.assertEqual(result['res_model'], 'dms.product')
        new_sku = self.env['dms.product'].browse(result['res_id'])
        self.assertEqual(new_sku.template_id, template)
        self.assertEqual(new_sku.production_year, '2027')

        # 驗證 wizard 邏輯：有衝突時顯示警告，再呼叫 action_confirm_create 才建立
        wizard2 = self.env['dms.product.duplicate.wizard'].create({
            'source_product_id': sku.id,
            'production_year': '2026',  # 與原始 sku 相同年份，應觸發衝突
        })
        conflict_result = wizard2.action_check_and_create()
        self.assertEqual(conflict_result['res_model'], 'dms.product.duplicate.wizard')
        self.assertTrue(wizard2.has_conflict)
        self.assertTrue(wizard2.conflict_product_name)
        confirmed = wizard2.action_confirm_create()
        self.assertEqual(confirmed['res_model'], 'dms.product')
        confirmed_sku = self.env['dms.product'].browse(confirmed['res_id'])
        self.assertEqual(confirmed_sku.production_year, '2026')

    def test_11_direct_sku_copy_carries_colors_and_clears_year(self):
        template = self.env['dms.product.template'].create({
            'brand_id': self.brand.id,
            'family_name': '測試車系 H',
            'type_name': '雙碟',
            'model_name': 'TSTCPY2',
            'energy_type': 'oil',
        })
        sku = self.env['dms.product'].create({
            'template_id': template.id,
            'production_year': '2026',
            'color': '消光灰',
            'active': True,
        })

        copied_sku = sku.copy({'template_id': template.id})

        self.assertEqual(copied_sku.template_id, template)
        self.assertFalse(copied_sku.production_year)
        self.assertFalse(copied_sku.internal_code)
        self.assertEqual(copied_sku.color_ids.name, sku.color_ids.name)
        self.assertEqual(copied_sku.color, sku.color)

    def test_12_open_color_editor_returns_modal_form(self):
        template = self.env['dms.product.template'].create({
            'brand_id': self.brand.id,
            'family_name': '測試車系 I',
            'type_name': '雙碟',
            'model_name': 'TSTCLR1',
            'energy_type': 'oil',
        })
        product = self.env['dms.product'].create({
            'template_id': template.id,
            'production_year': '2026',
            'active': True,
        })

        action = product.action_open_color_editor()

        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'dms.product')
        self.assertEqual(action['res_id'], product.id)
        self.assertEqual(action['target'], 'new')
        self.assertEqual(action['view_mode'], 'form')

    def test_13_color_summary_updates_after_color_unlink(self):
        template = self.env['dms.product.template'].create({
            'brand_id': self.brand.id,
            'family_name': '測試車系 J',
            'type_name': '雙碟',
            'model_name': 'TSTCLR2',
            'energy_type': 'oil',
        })
        product = self.env['dms.product'].create({
            'template_id': template.id,
            'production_year': '2026',
            'color': '泰奶紅、鈦灰',
            'active': True,
        })

        color_to_remove = product.color_ids.filtered(lambda color: color.name == '鈦灰')
        self.assertTrue(color_to_remove)

        color_to_remove.unlink()
        product.invalidate_recordset(['color'])

        self.assertEqual(product.color, '泰奶紅')
