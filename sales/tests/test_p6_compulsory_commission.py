"""UAT p6（使用者 2026-11-06 選 A）：微型電動二輪車強制險傭金固定 100（三年期）；
油車、電動車、輕型電動車照舊一年 145、兩年 215。領牌前自動帶入、領牌完成鎖定、人工改過不覆寫。"""
from decimal import Decimal

from django.utils import timezone

from sales.models import OrderOperationsProfile, VehicleColor, VehicleModel
from sales.services.incentive_rule import apply_order_incentive_rule
from sales.tests import test_finance_ledger as ledger


class CompulsoryCommissionTests(ledger.FinanceLedgerTestBase):
    def order_for(self, energy, period):
        model = VehicleModel.objects.create(brand="SYM", name=f"傭金{energy}{period}", energy_type=energy)
        color = VehicleColor.objects.create(vehicle_model=model, name="白")
        return self.make_order(vehicle_model=model, color=color, compulsory_insurance_period=period)

    def test_micro_electric_commission_is_100_whatever_the_period(self):
        for period in (1, 2, 3):
            order = self.order_for(VehicleModel.EnergyType.MICRO_ELECTRIC, period)
            self.assertEqual(apply_order_incentive_rule(order).insurance_commission, Decimal("100"))

    def test_other_energy_types_keep_145_and_215(self):
        for energy in (VehicleModel.EnergyType.GAS, VehicleModel.EnergyType.ELECTRIC, VehicleModel.EnergyType.LIGHT_ELECTRIC):
            for period, expected in ((1, Decimal("145")), (2, Decimal("215"))):
                order = self.order_for(energy, period)
                self.assertEqual(apply_order_incentive_rule(order).insurance_commission, expected, (energy, period))

    def test_micro_commission_respects_manual_value_and_registration_lock(self):
        order = self.order_for(VehicleModel.EnergyType.MICRO_ELECTRIC, 3)
        profile, _created = OrderOperationsProfile.objects.get_or_create(order=order)
        OrderOperationsProfile.objects.filter(pk=profile.pk).update(
            insurance_commission=Decimal("80"), manual_financial_fields=["insurance_commission"])
        self.assertEqual(apply_order_incentive_rule(order).insurance_commission, Decimal("80"))
        OrderOperationsProfile.objects.filter(pk=profile.pk).update(
            insurance_commission=Decimal("0"), manual_financial_fields=[], incentive_locked_at=timezone.now())
        self.assertEqual(apply_order_incentive_rule(order).insurance_commission, Decimal("0"), "領牌完成已鎖定")
