"""T-157（使用者 2026-11-13 選 A）：強制險傭金建單就帶入，人工改過的值不再被重算覆蓋。
金額規則不變（一年 145、兩年 215、微電 100），既有訂單不回填。"""
from decimal import Decimal

from django import forms
from django.urls import reverse
from django.utils import timezone

from sales.forms import OrderOperationsForm
from sales.models import OrderOperationsProfile, SalesOrder, VehicleColor, VehicleModel
from sales.services.financial_refresh import refresh_unlocked_financials
from sales.services.operations_sync import sync_order_operations
from sales.tests import test_finance_ledger as ledger


class CompulsoryCommissionPrefillTests(ledger.FinanceLedgerTestBase):
    def order_for(self, energy, period=1):
        model = VehicleModel.objects.create(brand="SYM", name=f"T157{energy}{period}", energy_type=energy)
        color = VehicleColor.objects.create(vehicle_model=model, name="白")
        return self.make_order(vehicle_model=model, color=color, compulsory_insurance_period=period)

    def test_new_order_gets_commission_at_creation(self):
        self.assertEqual(self.profile(self.make_order()).insurance_commission, Decimal("145"))
        self.assertEqual(self.profile(self.make_order(compulsory_insurance_period=2)).insurance_commission, Decimal("215"))

    def test_other_energy_types_keep_current_amounts_at_creation(self):
        cases = (
            (VehicleModel.EnergyType.ELECTRIC, 1, Decimal("145")),
            (VehicleModel.EnergyType.LIGHT_ELECTRIC, 1, Decimal("145")),
            (VehicleModel.EnergyType.MICRO_ELECTRIC, 3, Decimal("100")),
        )
        for energy, period, expected in cases:
            self.assertEqual(self.profile(self.order_for(energy, period)).insurance_commission, expected, energy)

    def test_period_without_rule_is_left_untouched(self):
        # 非微電三年期沒有規則：維持原值，不帶 0 也不帶其他金額。
        self.assertEqual(self.profile(self.make_order(compulsory_insurance_period=3)).insurance_commission, Decimal("0"))

    def test_locked_order_is_not_refilled_by_sync(self):
        order = self.make_order()
        OrderOperationsProfile.objects.filter(order=order).update(
            insurance_commission=Decimal("0"), incentive_locked_at=timezone.now())
        sync_order_operations(order.pk)
        self.assertEqual(self.profile(order).insurance_commission, Decimal("0"))

    def test_cancelled_order_is_not_refilled_by_sync(self):
        order = self.make_order()
        OrderOperationsProfile.objects.filter(order=order).update(insurance_commission=Decimal("0"))
        SalesOrder.objects.filter(pk=order.pk).update(status=SalesOrder.Status.CANCELLED)
        sync_order_operations(order.pk)
        self.assertEqual(self.profile(order).insurance_commission, Decimal("0"))

    def post_operations(self, order, **changes):
        profile = self.profile(order)
        form = OrderOperationsForm(instance=profile, prefix="operations")
        payload = {}
        for field in form:
            if isinstance(field.field, forms.FileField):
                continue
            if isinstance(field.field, forms.BooleanField):
                if field.value():
                    payload[field.html_name] = "on"
            else:
                payload[field.html_name] = "" if field.value() is None else str(field.value())
        payload.update({"payments-TOTAL_FORMS": "0", "payments-INITIAL_FORMS": "0"})
        payload.update({f"operations-{name}": value for name, value in changes.items()})
        return self.client.post(reverse("order_operations", args=[order.pk]), payload)

    def test_manual_commission_survives_refresh(self):
        self.client.force_login(self.admin)
        order = self.make_order()
        response = self.post_operations(order, insurance_commission="200")
        self.assertEqual(response.status_code, 302, getattr(response, "context", None))
        profile = self.profile(order)
        self.assertEqual(profile.insurance_commission, Decimal("200"))
        self.assertIn("insurance_commission", profile.manual_financial_fields)
        refresh_unlocked_financials(order.pk)
        sync_order_operations(order.pk)
        self.assertEqual(self.profile(order).insurance_commission, Decimal("200"))

    def test_finance_row_shows_source_tag(self):
        self.client.force_login(self.admin)
        order = self.make_order()
        page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        finance = page.split('id="panel-finance"', 1)[1].split('id="panel-delivery"', 1)[0]
        row = finance.split('name="operations-insurance_commission"', 1)[0].rsplit("data-ledger-row", 1)[1]
        self.assertIn("系統帶入", row)
