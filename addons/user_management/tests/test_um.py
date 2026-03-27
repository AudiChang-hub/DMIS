"""
user_management.tests.test_um
---
自訂存取群組（um.access.group）功能測試：
- 菜單白名單過濾
- 多群組聯集邏輯
- 管理員不受限
- cache 失效
"""

from odoo.tests.common import TransactionCase


class TestUmAccessGroup(TransactionCase):
    """um.access.group 核心邏輯測試"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # ── 取得現有菜單（用 base 模組的菜單，保證一定存在）──────────
        # 找一個有子菜單的根菜單
        cls.menu_root = cls.env['ir.ui.menu'].search(
            [('parent_id', '=', False)], order='id', limit=1
        )
        cls.menu_child = cls.env['ir.ui.menu'].search(
            [('parent_id', '=', cls.menu_root.id)], order='id', limit=1
        )
        # 確保有足夠的測試菜單
        cls.all_root_menus = cls.env['ir.ui.menu'].search(
            [('parent_id', '=', False)]
        )

        # ── 建立測試使用者（internal user）────────────────────────────
        group_user = cls.env.ref('base.group_user')
        cls.test_user_a = cls.env['res.users'].create({
            'name': 'UM 測試使用者 A',
            'login': 'test_um_user_a',
            'email': 'um_a@test.com',
            'groups_id': [(4, group_user.id)],
        })
        cls.test_user_b = cls.env['res.users'].create({
            'name': 'UM 測試使用者 B',
            'login': 'test_um_user_b',
            'email': 'um_b@test.com',
            'groups_id': [(4, group_user.id)],
        })

        # ── 建立自訂存取群組 ──────────────────────────────────────────
        # 群組 X：只含第一個根菜單
        cls.um_group_x = cls.env['um.access.group'].create({
            'name': 'UM 測試群組 X',
            'menu_ids': [(6, 0, [cls.menu_root.id])],
        })
        # 群組 Y：只含第二個根菜單（若有）
        second_root = cls.env['ir.ui.menu'].search(
            [('parent_id', '=', False)], order='id', offset=1, limit=1
        )
        cls.menu_root_2 = second_root
        cls.um_group_y = cls.env['um.access.group'].create({
            'name': 'UM 測試群組 Y',
            'menu_ids': [(6, 0, [second_root.id] if second_root else [])],
        })
        # 空群組（無菜單）
        cls.um_group_empty = cls.env['um.access.group'].create({
            'name': 'UM 空群組',
            'menu_ids': [(6, 0, [])],
        })

    # ── 測試 01：無 um_group_ids 時不施加額外限制 ─────────────────────

    def test_01_no_um_group_no_restriction(self):
        """使用者無 um_group_ids：可見菜單與 Odoo 原生相同"""
        # test_user_a 目前無 um_group_ids
        self.assertFalse(self.test_user_a.um_group_ids)

        odoo_visible = self.env['ir.ui.menu']._visible_menu_ids()
        um_visible = self.env['ir.ui.menu'].with_user(self.test_user_a)._visible_menu_ids()

        # 兩者應相同（internal user 看到相同菜單）
        self.assertEqual(
            set(um_visible),
            set(
                self.env['ir.ui.menu']
                .with_user(self.test_user_a)
                .with_context({'ir.ui.menu.full_list': True})
                ._visible_menu_ids()
            ),
            '無 um_group_ids 時，_visible_menu_ids 不應被額外過濾',
        )

    # ── 測試 02：指派單一群組後僅見允許菜單 ──────────────────────────

    def test_02_single_group_filters_menus(self):
        """指派 um_group_x（含 menu_root）後，使用者只見 menu_root 及其子菜單"""
        self.test_user_a.write({'um_group_ids': [(6, 0, [self.um_group_x.id])]})
        self.env['ir.ui.menu'].clear_caches()

        visible = self.env['ir.ui.menu'].with_user(self.test_user_a)._visible_menu_ids()
        visible_set = set(visible)

        # menu_root 應可見（直接允許）
        self.assertIn(self.menu_root.id, visible_set,
                      'um_group_x 允許的根菜單應可見')

        # 若存在其他根菜單，皆不應可見
        other_roots = self.all_root_menus - self.menu_root
        for m in other_roots:
            self.assertNotIn(m.id, visible_set,
                             f'其他根菜單 {m.name} 不應可見')

        # 清除，避免影響其他測試
        self.test_user_a.write({'um_group_ids': [(5, 0)]})
        self.env['ir.ui.menu'].clear_caches()

    # ── 測試 03：多群組聯集 ─────────────────────────────────────────

    def test_03_multiple_groups_union(self):
        """指派 um_group_x + um_group_y，可見菜單為兩個群組的聯集"""
        if not self.menu_root_2:
            self.skipTest('系統菜單數量不足，跳過此測試')

        self.test_user_b.write({
            'um_group_ids': [(6, 0, [self.um_group_x.id, self.um_group_y.id])]
        })
        self.env['ir.ui.menu'].clear_caches()

        visible = set(
            self.env['ir.ui.menu'].with_user(self.test_user_b)._visible_menu_ids()
        )

        self.assertIn(self.menu_root.id, visible, '群組 X 的菜單應可見')
        self.assertIn(self.menu_root_2.id, visible, '群組 Y 的菜單應可見')

        self.test_user_b.write({'um_group_ids': [(5, 0)]})
        self.env['ir.ui.menu'].clear_caches()

    # ── 測試 04：空群組無可見菜單 ─────────────────────────────────────

    def test_04_empty_group_no_menus(self):
        """指派空群組（無 menu_ids）時，使用者看不到任何菜單"""
        self.test_user_a.write({'um_group_ids': [(6, 0, [self.um_group_empty.id])]})
        self.env['ir.ui.menu'].clear_caches()

        visible = self.env['ir.ui.menu'].with_user(self.test_user_a)._visible_menu_ids()
        self.assertEqual(visible, [], '空群組時應回傳空清單')

        self.test_user_a.write({'um_group_ids': [(5, 0)]})
        self.env['ir.ui.menu'].clear_caches()

    # ── 測試 05：系統管理員不受 um 群組限制 ──────────────────────────

    def test_05_system_admin_bypass(self):
        """擁有 base.group_system 的使用者不受 um 群組限制"""
        group_system = self.env.ref('base.group_system')
        admin_user = self.env['res.users'].create({
            'name': 'UM 測試管理員',
            'login': 'test_um_admin',
            'email': 'um_admin@test.com',
            'groups_id': [(4, group_system.id)],
            'um_group_ids': [(6, 0, [self.um_group_empty.id])],  # 空群組
        })
        self.env['ir.ui.menu'].clear_caches()

        # 即使指派空群組，管理員仍應看到公用菜單
        visible = self.env['ir.ui.menu'].with_user(admin_user)._visible_menu_ids()
        self.assertTrue(len(visible) > 0, '系統管理員不應受空 um 群組影響')

    # ── 測試 06：修改 menu_ids 觸發 cache 失效 ────────────────────────

    def test_06_write_menu_ids_clears_cache(self):
        """修改 um_group 的 menu_ids 時，應呼叫 clear_caches（不拋出例外即可）"""
        try:
            self.um_group_x.write({
                'menu_ids': [(6, 0, [self.menu_root.id])]
            })
        except Exception as e:
            self.fail(f'修改 menu_ids 時不應拋出例外：{e}')

    # ── 測試 07：修改 user.um_group_ids 觸發 cache 失效 ──────────────

    def test_07_write_user_um_groups_clears_cache(self):
        """修改使用者的 um_group_ids 時，應呼叫 clear_caches（不拋出例外即可）"""
        try:
            self.test_user_a.write({
                'um_group_ids': [(4, self.um_group_x.id)]
            })
            self.test_user_a.write({'um_group_ids': [(5, 0)]})
        except Exception as e:
            self.fail(f'修改 um_group_ids 時不應拋出例外：{e}')

    # ── 測試 08：子菜單被允許時，祖先自動可見 ────────────────────────

    def test_08_child_menu_includes_ancestors(self):
        """um_group 僅含子菜單時，祖先菜單應自動加入可見清單供導航"""
        if not self.menu_child:
            self.skipTest('無子菜單可供測試，跳過')

        # 建立只含子菜單的群組
        group_child_only = self.env['um.access.group'].create({
            'name': 'UM 子菜單群組',
            'menu_ids': [(6, 0, [self.menu_child.id])],
        })
        self.test_user_a.write({'um_group_ids': [(6, 0, [group_child_only.id])]})
        self.env['ir.ui.menu'].clear_caches()

        visible = set(
            self.env['ir.ui.menu'].with_user(self.test_user_a)._visible_menu_ids()
        )

        self.assertIn(self.menu_child.id, visible, '子菜單本身應可見')
        self.assertIn(self.menu_root.id, visible, '子菜單的父（根）菜單應自動可見')

        self.test_user_a.write({'um_group_ids': [(5, 0)]})
        self.env['ir.ui.menu'].clear_caches()
