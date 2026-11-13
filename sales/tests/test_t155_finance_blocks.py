"""T-155（使用者 2026-11-12 簡報 p4、p5）收入與支出區塊整理。

p4：「成交金額與尾款試算」與「尾款計算」小卡已在 1.87.0 拿掉（見 test_t137_finance_layout）；
「內部折扣」改成獨立一整列，有牌險差異時差異卡在下一列，不再並排。
p5：領牌合計改標「稅金總額＋強制險費用」並列出拆解，例 715＋658＝1,373；只改顯示，不改試算。"""
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.conf import settings

from sales.tests import test_finance_ledger as ledger


class FinanceBlocksT155Tests(ledger.FinanceLedgerTestBase):
    setUp = ledger.FinanceStepPageTests.setUp
    finance_panel = ledger.FinanceStepPageTests.finance_panel

    def registration_fields(self, **overrides):
        # 2026/11/09 領牌、125 c.c.：號牌 300＋行照 150＋檢驗 200＋公路養管 65＋牌照稅 0＝715，強制險 658，合計 1,373。
        fields = dict(
            registration_date=date(2026, 11, 9), registration_rate_class="M2",
            registration_plate_fee=300, registration_license_fee=150, registration_inspection_fee=200,
            road_maintenance_fee=65, license_tax_fee=0, compulsory_insurance_fee=658,
            registration_calculated_total=Decimal("1373"), plate_insurance_fee=Decimal("1373"),
        )
        fields.update(overrides)
        return fields

    def registration_card(self, order):
        _page, finance = self.finance_panel(order)
        return finance.split('aria-label="領牌試算"', 1)[1].split("</section>", 1)[0]

    def test_registration_total_reads_as_tax_plus_compulsory_insurance(self):
        order = self.make_order(**self.registration_fields())
        self.assertEqual(order.registration_tax_total, 715)
        card = self.registration_card(order)
        self.assertIn("<span>稅金總額＋強制險費用</span>", card)
        self.assertIn("稅金 $715 ＋ 強制險 $658 ＝</small> $1,373", card)
        self.assertNotIn("<span>試算合計</span>", card)
        # 分項照舊列出，計算不變。
        for label in ("號牌", "行照", "檢驗", "公路養管", "牌照稅", "強制險"):
            self.assertIn(f"<span>{label}</span>", card)

    def test_fixed_bundle_keeps_single_total(self):
        # 固定整包規則沒有分項、強制險含在整包裡，不拆成稅金＋強制險。
        order = self.make_order(**self.registration_fields(
            registration_plate_fee=0, registration_license_fee=0, registration_inspection_fee=0,
            road_maintenance_fee=0, compulsory_insurance_fee=0,
            registration_calculated_total=Decimal("1888"), plate_insurance_fee=Decimal("1888"),
        ))
        card = self.registration_card(order)
        self.assertIn("<span>試算合計</span>", card)
        self.assertIn("$1,888", card)
        self.assertNotIn("稅金總額＋強制險費用", card)

    def test_internal_discount_is_its_own_row(self):
        # 牌險費少於試算才有差異卡（T-168）。
        order = self.make_order(**self.registration_fields(plate_insurance_fee=Decimal("1300")))
        _page, finance = self.finance_panel(order)
        strip = finance.split('<div class="finance-strip', 1)[1].split('id="finance-receipts"', 1)[0]
        self.assertTrue(strip.startswith('">'), "finance-strip 不再帶 has-variance 並排樣式")
        self.assertIn('id="internal-discount-title"', strip)
        self.assertIn('id="plate-variance-title"', strip)
        css = (Path(settings.BASE_DIR) / "static/css/order-finance.css").read_text(encoding="utf-8")
        self.assertNotIn(".finance-strip.has-variance", css)
        self.assertIn(".finance-strip { display: grid; grid-template-columns: minmax(0, 1fr);", css)
