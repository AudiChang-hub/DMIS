"""
dms_core.tests.test_dealer
---
單元測試：dms.dealer 車行模型基本邏輯
"""

from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestDealerManagerSync(TransactionCase):
    """測試「店長同負責人」同步邏輯"""

    def setUp(self):
        super().setUp()
        # 先建一個車行類型供測試使用
        self.dealer_type = self.env['dms.dealer.type'].create({
            'name': '加盟',
            'code': 'JM',
        })

    # ------------------------------------------------------------------
    # create() 同步
    # ------------------------------------------------------------------

    def test_create_manager_same_as_owner_true(self):
        """建立時若勾選同負責人且未填店長，店長應自動帶入負責人姓名"""
        dealer = self.env['dms.dealer'].create({
            'name': '測試車行',
            'owner_name': '王大明',
            'store_manager': '',
            'manager_same_as_owner': True,
        })
        self.assertEqual(dealer.store_manager, '王大明',
                         '建立時 store_manager 應自動同步為 owner_name')

    def test_create_manager_same_as_owner_false(self):
        """未勾選同負責人時，店長維持原值不被覆寫"""
        dealer = self.env['dms.dealer'].create({
            'name': '測試車行B',
            'owner_name': '陳大花',
            'store_manager': '李老闆',
            'manager_same_as_owner': False,
        })
        self.assertEqual(dealer.store_manager, '李老闆',
                         '未勾選時 store_manager 不應被覆寫')

    # ------------------------------------------------------------------
    # write() 同步
    # ------------------------------------------------------------------

    def test_write_owner_change_while_same_checked(self):
        """勾選同負責人後修改負責人姓名，店長應同步更新"""
        dealer = self.env['dms.dealer'].create({
            'name': '測試車行C',
            'owner_name': '初始姓名',
            'store_manager': '初始姓名',
            'manager_same_as_owner': True,
        })
        dealer.write({'owner_name': '新負責人', 'manager_same_as_owner': True})
        self.assertEqual(dealer.store_manager, '新負責人',
                         'write 時若 manager_same_as_owner=True 且 owner_name 變更，store_manager 應同步')

    def test_uncheck_manager_same_preserves_manager(self):
        """取消勾選後，店長姓名應保留不被清空"""
        dealer = self.env['dms.dealer'].create({
            'name': '測試車行D',
            'owner_name': '趙老闆',
            'store_manager': '趙老闆',
            'manager_same_as_owner': True,
        })
        dealer.write({'manager_same_as_owner': False})
        # 店長不應被自動清空
        self.assertEqual(dealer.store_manager, '趙老闆',
                         '取消同步後 store_manager 應保留原值')

    # ------------------------------------------------------------------
    # Many2many 品牌
    # ------------------------------------------------------------------

    def test_brand_many2many(self):
        """brand_ids Many2many 儲存後應可正確讀取"""
        brand_sym = self.env['dms.brand'].create({'name': '三陽'})
        brand_suzuki = self.env['dms.brand'].create({'name': '台鈴'})

        dealer = self.env['dms.dealer'].create({
            'name': '多品牌車行',
            'owner_name': '林老闆',
            'store_manager': '林老闆',
            'brand_ids': [(4, brand_sym.id), (4, brand_suzuki.id)],
        })

        self.assertIn(brand_sym, dealer.brand_ids,
                      '三陽品牌應出現在 brand_ids')
        self.assertIn(brand_suzuki, dealer.brand_ids,
                      '台鈴品牌應出現在 brand_ids')
        self.assertEqual(len(dealer.brand_ids), 2,
                         'brand_ids 應有 2 筆')

    def test_brand_ids_persist_after_reload(self):
        """重新從 DB 讀取後 brand_ids 應仍存在"""
        brand = self.env['dms.brand'].create({'name': '山葉'})
        dealer = self.env['dms.dealer'].create({
            'name': '山葉車行',
            'owner_name': '吳老闆',
            'store_manager': '吳老闆',
            'brand_ids': [(4, brand.id)],
        })
        # 清除 cache，強制從 DB 讀取
        dealer.invalidate_recordset()
        self.assertEqual(len(dealer.brand_ids), 1,
                         '重新讀取後 brand_ids 應仍有 1 筆')

    # ------------------------------------------------------------------
    # code 唯一性
    # ------------------------------------------------------------------

    def test_code_unique_constraint(self):
        """重複 code 建立時應觸發唯一性錯誤"""
        self.env['dms.dealer'].create({
            'code': 'DUPTEST01',
            'name': '車行甲',
            'owner_name': '甲老闆',
            'store_manager': '甲老闆',
        })
        with self.assertRaises(Exception,
                               msg='重複 code 應觸發 IntegrityError 或 UserError'):
            self.env['dms.dealer'].create({
                'code': 'DUPTEST01',
                'name': '車行乙',
                'owner_name': '乙老闆',
                'store_manager': '乙老闆',
            })

    # ------------------------------------------------------------------
    # dispatch_capacity 不可為負數
    # ------------------------------------------------------------------

    def test_negative_dispatch_capacity_raises(self):
        """排車容量為負數時應觸發 ValidationError"""
        with self.assertRaises(ValidationError):
            self.env['dms.dealer'].create({
                'name': '排車車行',
                'owner_name': '負號老闆',
                'store_manager': '負號老闆',
                'sym_dispatch_capacity': -1,
            })
