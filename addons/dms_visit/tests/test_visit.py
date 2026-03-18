from odoo.tests.common import TransactionCase
from odoo import fields
from odoo.exceptions import AccessError


class TestDmsVisit(TransactionCase):
    """dms_visit 模組單元測試"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # ── 基礎資料 ─────────────────────────────────────────────
        cls.brand = cls.env['dms.brand'].create({'name': '測試品牌'})

        cls.dealer = cls.env['dms.dealer'].create({
            'name': '測試車行',
            'owner_name': '測試負責人',
            'address': '台北市中正區測試路1號',
            'phone_1': '02-12345678',
        })

        cls.product = cls.env['dms.product'].create({
            'brand_id': cls.brand.id,
            'name': '測試車款',
            'model': 'TEST-001',
            'year': '2024',
            'energy_type': 'oil',
        })

        cls.purpose = cls.env['dms.visit.purpose'].create({
            'name': '洽談訂單',
            'code': 'TALK',
        })

        # ── 群組參考 ──────────────────────────────────────────────
        group_visit_user = cls.env.ref('dms_visit.group_dms_visit_user')
        group_visit_admin = cls.env.ref('dms_visit.group_dms_visit_admin')

        # ── 建立測試使用者 ────────────────────────────────────────
        cls.user_visit1 = cls.env['res.users'].create({
            'name': '拜訪使用者A',
            'login': 'test_visit_user_a',
            'email': 'visit_a@test.com',
            'groups_id': [(4, group_visit_user.id)],
        })

        cls.user_visit2 = cls.env['res.users'].create({
            'name': '拜訪使用者B',
            'login': 'test_visit_user_b',
            'email': 'visit_b@test.com',
            'groups_id': [(4, group_visit_user.id)],
        })

        cls.user_admin = cls.env['res.users'].create({
            'name': '拜訪管理者',
            'login': 'test_visit_admin',
            'email': 'visit_admin@test.com',
            'groups_id': [(4, group_visit_admin.id)],
        })

    # ── Test 01：必填欄位 ──────────────────────────────────────────
    def test_01_visit_required_fields(self):
        """新增拜訪紀錄並確認必填欄位（visit_date、dealer_id、visitor_id）"""
        visit = self.env['dms.visit'].create({
            'visit_date': fields.Datetime.now(),
            'dealer_id': self.dealer.id,
            'visitor_id': self.env.user.id,
            'purpose_id': self.purpose.id,
        })
        self.assertTrue(visit.id, '應成功建立拜訪紀錄')
        self.assertEqual(visit.state, 'draft', '預設狀態應為草稿')
        self.assertIn('拜訪', visit.name, 'computed name 應包含「拜訪」')
        self.assertIn(self.dealer.name, visit.name, 'computed name 應包含車行名稱')

    # ── Test 02：車行拜訪計數 ────────────────────────────────────────
    def test_02_visit_count_on_dealer(self):
        """車行 Smart Button 計數：新增拜訪後 visit_count 正確遞增"""
        initial_count = self.dealer.visit_count

        self.env['dms.visit'].create({
            'visit_date': fields.Datetime.now(),
            'dealer_id': self.dealer.id,
            'visitor_id': self.env.user.id,
        })

        self.dealer.invalidate_recordset()
        self.assertEqual(
            self.dealer.visit_count, initial_count + 1,
            '新增一筆拜訪後，visit_count 應增加 1',
        )

    # ── Test 03：送出物品明細 ────────────────────────────────────────
    def test_03_items_delivered(self):
        """拜訪送出物品：新增 item_ids 後數量與備註正確儲存"""
        visit = self.env['dms.visit'].create({
            'visit_date': fields.Datetime.now(),
            'dealer_id': self.dealer.id,
            'visitor_id': self.env.user.id,
            'item_ids': [(0, 0, {
                'product_id': self.product.id,
                'quantity': 3.0,
                'note': '測試送出物品備註',
            })],
        })
        self.assertEqual(len(visit.item_ids), 1, '應有 1 筆物品明細')
        self.assertEqual(visit.item_ids[0].quantity, 3.0, '數量應為 3.0')
        self.assertEqual(
            visit.item_ids[0].note, '測試送出物品備註', '備註應正確儲存',
        )
        self.assertEqual(
            visit.item_ids[0].product_id.id, self.product.id, '產品應正確關聯',
        )

    # ── Test 04：Record Rule — user 只見自己的拜訪 ──────────────────
    def test_04_record_rule_user_see_own(self):
        """Record Rule：group_dms_visit_user 只能查看自己（visitor_id）的拜訪"""
        # 建立兩位使用者各自的拜訪紀錄（以 superuser 建立，繞過 record rule）
        visit_a = self.env['dms.visit'].create({
            'visit_date': fields.Datetime.now(),
            'dealer_id': self.dealer.id,
            'visitor_id': self.user_visit1.id,
        })
        visit_b = self.env['dms.visit'].create({
            'visit_date': fields.Datetime.now(),
            'dealer_id': self.dealer.id,
            'visitor_id': self.user_visit2.id,
        })

        # user_visit1 的視角：只應看到自己的 visit_a
        visible_a = self.env['dms.visit'].with_user(self.user_visit1).search([
            ('id', 'in', [visit_a.id, visit_b.id]),
        ])
        self.assertIn(visit_a, visible_a, 'user_visit1 應能看到自己的拜訪')
        self.assertNotIn(visit_b, visible_a, 'user_visit1 不應看到 user_visit2 的拜訪')

    # ── Test 05：Record Rule — admin 可見所有拜訪 ───────────────────
    def test_05_record_rule_admin_see_all(self):
        """Record Rule：group_dms_visit_admin 可查看所有拜訪"""
        visit_a = self.env['dms.visit'].create({
            'visit_date': fields.Datetime.now(),
            'dealer_id': self.dealer.id,
            'visitor_id': self.user_visit1.id,
        })
        visit_b = self.env['dms.visit'].create({
            'visit_date': fields.Datetime.now(),
            'dealer_id': self.dealer.id,
            'visitor_id': self.user_visit2.id,
        })

        visible_admin = self.env['dms.visit'].with_user(self.user_admin).search([
            ('id', 'in', [visit_a.id, visit_b.id]),
        ])
        self.assertIn(visit_a, visible_admin, '管理者應能看到 user_visit1 的拜訪')
        self.assertIn(visit_b, visible_admin, '管理者應能看到 user_visit2 的拜訪')
