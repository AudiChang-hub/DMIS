from odoo.tests.common import TransactionCase
from odoo import fields


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

        cls.purpose_price = cls.env['dms.visit.purpose'].create({
            'name': '價格表發放',
            'code': 'PRICE',
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

    def _make_schedule(self, **kwargs):
        defaults = {
            'dealer_id': self.dealer.id,
            'purpose_id': self.purpose_price.id,
            'visitor_id': self.user_visit1.id,
            'interval_months': '1',
            'schedule_type': 'fixed_day',
            'day_of_month': 1,
        }
        defaults.update(kwargs)
        return self.env['dms.visit.schedule'].create(defaults)

    # ── Test 06：cron 為啟用車行建立拜訪 ────────────────────────────
    def test_06_cron_creates_visit_for_enabled_dealer(self):
        """cron 執行後：啟用中的排程應補齊未來拜訪草稿。"""
        schedule = self._make_schedule()
        expected_dates = schedule._generate_all_dates()

        self.env['dms.visit'].search([
            ('schedule_id', '=', schedule.id),
        ]).unlink()

        self.env['dms.dealer'].cron_generate_price_list_visits()

        visits = self.env['dms.visit'].sudo().search([
            ('schedule_id', '=', schedule.id),
            ('state', '=', 'draft'),
        ], order='visit_date asc')
        self.assertEqual(len(visits), len(expected_dates), 'cron 應補齊排程未來拜訪草稿')
        self.assertEqual(visits[0].visitor_id, self.user_visit1, '拜訪人員應為 price_list_visitor_id')
        self.assertTrue(visits[0].is_auto_generated, '自動補齊的拜訪應標記為排程建立')
        self.assertEqual(fields.Datetime.to_datetime(visits[0].visit_date).date(), expected_dates[0])

    # ── Test 07：cron 不重複建立同月份拜訪 ─────────────────────────
    def test_07_cron_no_duplicate_same_month(self):
        """cron 執行兩次：同一排程不應重複建立未來拜訪。"""
        schedule = self._make_schedule()
        expected_count = len(schedule._generate_all_dates())

        self.env['dms.visit'].search([
            ('schedule_id', '=', schedule.id),
        ]).unlink()

        # 執行兩次
        self.env['dms.dealer'].cron_generate_price_list_visits()
        self.env['dms.dealer'].cron_generate_price_list_visits()

        visits = self.env['dms.visit'].sudo().search([
            ('schedule_id', '=', schedule.id),
            ('state', '!=', 'cancel'),
        ])
        self.assertEqual(len(visits), expected_count, 'cron 執行兩次後，不應重複建立拜訪')

    # ── Test 08：inactive schedule 不產生拜訪 ───────────────────────
    def test_08_cron_skip_disabled_dealer(self):
        """cron 執行後：停用中的排程不應建立拜訪"""
        schedule = self._make_schedule(active=False)
        before_count = self.env['dms.visit'].sudo().search_count([
            ('schedule_id', '=', schedule.id),
        ])

        self.env['dms.dealer'].cron_generate_price_list_visits()

        after_count = self.env['dms.visit'].sudo().search_count([
            ('schedule_id', '=', schedule.id),
        ])
        self.assertEqual(before_count, after_count, '停用排程不應新增拜訪')
