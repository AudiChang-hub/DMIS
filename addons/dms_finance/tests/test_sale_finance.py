"""
tests/test_sale_finance.py — dms_finance 單元測試

測試涵蓋：
1. 重複建立財務結算應觸發 UserError
2. total_income / total_expense / net_profit 計算正確（含邊界值）
3. 自動帶入邏輯（行照費、保險費、選號費、傭金）
"""
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError


class TestSaleFinance(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # 取得或建立測試用品牌
        cls.brand = cls.env['dms.brand'].search([], limit=1)
        if not cls.brand:
            cls.brand = cls.env['dms.brand'].create({'name': '測試品牌'})

        # 建立測試車款
        cls.product = cls.env['dms.product'].create({
            'brand_id': cls.brand.id,
            'name': '測試車款',
            'energy_type': 'oil',
        })

        # 建立主要測試訂單（含牌險費、選號費、傭金）
        cls.order_with_fees = cls.env['dms.sale.order'].create({
            'customer_name': '測試客戶A',
            'product_id': cls.product.id,
            'fee_vehicle_registration': 1000,
            'fee_insurance': 2000,
            'fee_plate_selection': 500,
            'commission': 3000,
        })

    # ─────────────────────────────────────────────────────────────────
    # TC-01：重複建立應觸發 UserError
    # ─────────────────────────────────────────────────────────────────
    def test_duplicate_finance_raises_user_error(self):
        """同一銷售訂單不得建立兩筆財務結算，第二次應觸發 UserError。"""
        order = self.env['dms.sale.order'].create({
            'customer_name': '測試客戶_重複',
            'product_id': self.product.id,
        })
        self.env['dms.sale.finance'].create({'sale_order_id': order.id})
        with self.assertRaises(UserError):
            self.env['dms.sale.finance'].create({'sale_order_id': order.id})

    # ─────────────────────────────────────────────────────────────────
    # TC-02：計算欄位正確性
    # ─────────────────────────────────────────────────────────────────
    def test_total_computation(self):
        """total_income、total_expense、net_profit 計算應正確。"""
        order = self.env['dms.sale.order'].create({
            'customer_name': '測試計算',
            'product_id': self.product.id,
        })
        finance = self.env['dms.sale.finance'].create({'sale_order_id': order.id})
        # 清除自動帶入明細，進行乾淨測試
        finance.income_ids.unlink()
        finance.expense_ids.unlink()

        cat_income = self.env['dms.finance.category'].search(
            [('type', '=', 'income')], limit=1)
        cat_expense = self.env['dms.finance.category'].search(
            [('type', '=', 'expense')], limit=1)

        self.assertTrue(cat_income, '應至少存在一筆收入類別（請確認 finance_category_data.xml 已載入）')
        self.assertTrue(cat_expense, '應至少存在一筆支出類別')

        self.env['dms.sale.finance.income'].create({
            'finance_id': finance.id,
            'category_id': cat_income.id,
            'amount': 10000,
        })
        self.env['dms.sale.finance.expense'].create({
            'finance_id': finance.id,
            'category_id': cat_expense.id,
            'amount': 3000,
        })

        self.assertAlmostEqual(finance.total_income, 10000,
                               msg='total_income 應等於收入明細合計')
        self.assertAlmostEqual(finance.total_expense, 3000,
                               msg='total_expense 應等於支出明細合計')
        self.assertAlmostEqual(finance.net_profit, 7000,
                               msg='net_profit 應等於 total_income - total_expense')

    def test_zero_profit_on_empty_lines(self):
        """未填任何收支明細時，三個計算欄位應均為 0。"""
        order = self.env['dms.sale.order'].create({
            'customer_name': '測試零值',
            'product_id': self.product.id,
        })
        finance = self.env['dms.sale.finance'].create({'sale_order_id': order.id})
        finance.income_ids.unlink()
        finance.expense_ids.unlink()

        self.assertAlmostEqual(finance.total_income, 0)
        self.assertAlmostEqual(finance.total_expense, 0)
        self.assertAlmostEqual(finance.net_profit, 0)

    def test_negative_net_profit(self):
        """支出大於收入時，net_profit 應為負數。"""
        order = self.env['dms.sale.order'].create({
            'customer_name': '測試負利',
            'product_id': self.product.id,
        })
        finance = self.env['dms.sale.finance'].create({'sale_order_id': order.id})
        finance.income_ids.unlink()
        finance.expense_ids.unlink()

        cat_income = self.env['dms.finance.category'].search(
            [('type', '=', 'income')], limit=1)
        cat_expense = self.env['dms.finance.category'].search(
            [('type', '=', 'expense')], limit=1)

        self.env['dms.sale.finance.income'].create({
            'finance_id': finance.id, 'category_id': cat_income.id, 'amount': 1000,
        })
        self.env['dms.sale.finance.expense'].create({
            'finance_id': finance.id, 'category_id': cat_expense.id, 'amount': 5000,
        })

        self.assertAlmostEqual(finance.net_profit, -4000,
                               msg='支出大於收入時，淨利應為負數')

    # ─────────────────────────────────────────────────────────────────
    # TC-03：自動帶入邏輯
    # ─────────────────────────────────────────────────────────────────
    def test_auto_populate_plate_fee(self):
        """牌險費支出應自動帶入 fee_vehicle_registration + fee_insurance。"""
        cat = self.env['dms.finance.category'].search(
            [('code', '=', 'plate_fee_expense')], limit=1)
        self.assertTrue(cat, '類別 plate_fee_expense 應存在於系統中')

        finance = self.env['dms.sale.finance'].create({
            'sale_order_id': self.order_with_fees.id
        })
        plate_exp = finance.expense_ids.filtered(
            lambda e: e.category_id.code == 'plate_fee_expense')
        self.assertTrue(plate_exp, '牌險費支出明細應被自動建立')
        # 1000 + 2000 = 3000
        self.assertAlmostEqual(plate_exp[0].amount, 3000,
                               msg='牌險費支出金額應為 fee_vehicle_registration + fee_insurance')

    def test_auto_populate_plate_selection(self):
        """選號支出應自動帶入 fee_plate_selection。"""
        cat = self.env['dms.finance.category'].search(
            [('code', '=', 'plate_selection')], limit=1)
        self.assertTrue(cat, '類別 plate_selection 應存在')

        finance = self.env['dms.sale.finance'].create({
            'sale_order_id': self.order_with_fees.id
        })
        sel_exp = finance.expense_ids.filtered(
            lambda e: e.category_id.code == 'plate_selection')
        self.assertTrue(sel_exp, '選號支出明細應被自動建立')
        self.assertAlmostEqual(sel_exp[0].amount, 500)

    def test_auto_populate_commission(self):
        """車行傭金支出應自動帶入 commission。"""
        cat = self.env['dms.finance.category'].search(
            [('code', '=', 'dealer_commission')], limit=1)
        self.assertTrue(cat, '類別 dealer_commission 應存在')

        finance = self.env['dms.sale.finance'].create({
            'sale_order_id': self.order_with_fees.id
        })
        comm_exp = finance.expense_ids.filtered(
            lambda e: e.category_id.code == 'dealer_commission')
        self.assertTrue(comm_exp, '車行傭金支出明細應被自動建立')
        self.assertAlmostEqual(comm_exp[0].amount, 3000)

    def test_auto_populate_income_plate_fee(self):
        """牌險費收入應與牌險費支出相同金額被自動建立。"""
        cat = self.env['dms.finance.category'].search(
            [('code', '=', 'plate_fee_income')], limit=1)
        self.assertTrue(cat, '類別 plate_fee_income 應存在')

        finance = self.env['dms.sale.finance'].create({
            'sale_order_id': self.order_with_fees.id
        })
        plate_inc = finance.income_ids.filtered(
            lambda i: i.category_id.code == 'plate_fee_income')
        self.assertTrue(plate_inc, '牌險費收入明細應被自動建立')
        self.assertAlmostEqual(plate_inc[0].amount, 3000)

    def test_no_auto_populate_when_no_fees(self):
        """訂單無牌險費/選號費/傭金時，不應建立任何自動帶入明細。"""
        order = self.env['dms.sale.order'].create({
            'customer_name': '測試無費用',
            'product_id': self.product.id,
        })
        finance = self.env['dms.sale.finance'].create({'sale_order_id': order.id})
        self.assertFalse(
            finance.expense_ids,
            '訂單無費用時，支出明細應為空'
        )
        self.assertFalse(
            finance.income_ids,
            '訂單無費用時，收入明細應為空'
        )
