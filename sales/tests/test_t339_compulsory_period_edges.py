"""T-339（使用者 2026-11-28）：強制險期間的邊界。

- 微電車一律三年。已交車／匯入的舊單資料庫存一年時，畫面顯示三年；存檔時改存三年，
  但牌險、強制險保留完成時的金額，不重算，淨利、應收、傭金都不變。
- 其他車種：期間有改才重算（既有行為不變）。
前端選項與說明見 tests/frontend/order-insurance-period-t339.test.cjs。
"""
from datetime import date
from decimal import Decimal

from django.urls import reverse

from sales.models import BrandRegistrationFeeRule, OrderOperationsProfile, SalesOrder, VehicleColor, VehicleModel
from sales.services.registration_fee import normalized_insurance_period
from sales.tests import test_completed_order_corrections as corrections

FEE_FIELDS = (
    "registration_plate_fee", "registration_license_fee", "registration_inspection_fee", "road_maintenance_fee",
    "license_tax_fee", "compulsory_insurance_fee", "registration_calculated_total", "registration_rate_class",
    "plate_insurance_fee", "calculated_balance", "actual_balance",
)


class MicroElectricLegacyPeriodTests(corrections.CompletedOrderCorrectionTests):
    """沿用完成後修正測試的建單與送出方式；只跑本類別新增的測試。"""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.micro = VehicleModel.objects.create(brand="虛構微電", name="T339 微電車", energy_type=VehicleModel.EnergyType.MICRO_ELECTRIC)
        cls.micro_color = VehicleColor.objects.create(vehicle_model=cls.micro, name="白")
        # 有微電車固定規則：期間若被判成「有改」就會改成整包 2300 重算，測得出有沒有保留完成時金額。
        BrandRegistrationFeeRule.objects.create(
            brand="虛構微電", energy_type=VehicleModel.EnergyType.MICRO_ELECTRIC, insurance_period_years=3,
            calculation_type=BrandRegistrationFeeRule.CalculationType.FIXED_BUNDLE, fixed_total=Decimal("2300"),
            effective_from=date(2026, 1, 1),
        )

    def legacy_micro(self, status=SalesOrder.Status.COMPLETED):
        order = self.order(vehicle_model=self.micro, color=self.micro_color, status=status,
                           compulsory_insurance_period=1, compulsory_insurance_fee=Decimal("400"))
        order.calculated_balance = order.calculate_balance()
        order.save(update_fields=["calculated_balance"])
        return order

    def snapshot(self, order):
        order.refresh_from_db()
        profile = OrderOperationsProfile.objects.filter(order=order).first()
        money = None
        if profile:
            money = (profile.compulsory_insurance_expense, profile.compulsory_insurance_income,
                     profile.insurance_commission, profile.net_profit)
        return {name: getattr(order, name) for name in FEE_FIELDS}, money

    def test_normalized_period_only_changes_micro_electric(self):
        self.assertEqual(normalized_insurance_period(self.micro, 1), 3)
        for period in (1, 2, 3):
            self.assertEqual(normalized_insurance_period(self.model, period), period)
        self.assertEqual(normalized_insurance_period(None, 2), 2)

    def test_delivered_legacy_micro_saves_three_years_and_keeps_completed_amounts(self):
        for status in (SalesOrder.Status.COMPLETED, SalesOrder.Status.DELIVERED_DOCS_PENDING):
            with self.subTest(status=status):
                order = self.legacy_micro(status)
                before_fees, before_money = self.snapshot(order)
                self.assertIsNotNone(before_money)  # 有收支資料，淨利、傭金的比對才有意義
                # 畫面送回的是三年（前端顯示三年），只改備註。
                self.assert_saved(self.post(order, compulsory_insurance_period="3", note="T339 只改備註"), order)
                after_fees, after_money = self.snapshot(order)
                self.assertEqual(order.compulsory_insurance_period, 3)
                self.assertEqual(order.note, "T339 只改備註")
                # 牌險、強制險、應收保留完成時的金額；收支、傭金、淨利都不變。
                self.assertEqual(after_fees, before_fees)
                self.assertEqual(after_money, before_money)

    def test_delivered_legacy_micro_still_keeps_amounts_when_one_year_is_sent_back(self):
        order = self.legacy_micro()
        before_fees, before_money = self.snapshot(order)
        self.assert_saved(self.post(order, compulsory_insurance_period="1", note="T339 舊值送回"), order)
        after_fees, after_money = self.snapshot(order)
        self.assertEqual(order.compulsory_insurance_period, 3)
        self.assertEqual((after_fees, after_money), (before_fees, before_money))

    def test_order_page_renders_stored_value_with_note_slot(self):
        order = self.legacy_micro()
        page = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "order"}).content.decode()
        field = page.split('<select name="compulsory_insurance_period"', 1)[1].split("</select>", 1)[0]
        # 伺服器輸出照資料庫的一年選取，前端才知道原值、載入後顯示三年並說明。
        self.assertIn('value="1" selected', field)
        self.assertIn("data-insurance-period-note", page)

    def test_gas_delivered_order_period_change_still_recalculates(self):
        # 其他車種不受影響：已交車的油車改期間照舊重算強制險（一年 658 → 兩年 1200）。
        self.model.displacement_cc = 124
        self.model.save(update_fields=["displacement_cc"])
        order = self.order(compulsory_insurance_period=1, compulsory_insurance_fee=Decimal("658"))
        self.assert_saved(self.post(order, note="只改備註"), order)
        self.assertEqual((order.compulsory_insurance_period, order.compulsory_insurance_fee), (1, 658))
        self.assert_saved(self.post(order, compulsory_insurance_period="2", note="改兩年"), order)
        self.assertEqual((order.compulsory_insurance_period, order.compulsory_insurance_fee), (2, 1200))

# 父類別的測試不在這裡重跑（設成 None，unittest 只收可呼叫的 test_*）。
for _name in [n for n in dir(corrections.CompletedOrderCorrectionTests) if n.startswith("test_")]:
    if _name not in MicroElectricLegacyPeriodTests.__dict__:
        setattr(MicroElectricLegacyPeriodTests, _name, None)
