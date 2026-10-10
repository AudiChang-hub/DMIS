"""1.63.0：領牌前以訂單日預估車輛成本；選號費在訂車時填寫並計入牌險合計與收支。"""
from datetime import date
from decimal import Decimal
from importlib import import_module

from django.apps import apps as django_apps
from django.test import TestCase

from sales.forms import OrderEditForm
from sales.models import OrderOperationsProfile, OtherFeeLine, SalesOrder, VehicleSettlementCostRule
from sales.services.customer_receivable import default_customer_balance
from sales.services.operations_sync import sync_order_operations
from sales.services.settlement_cost import apply_order_settlement_cost
from sales.tests import test_completed_order_corrections as correction_tests


class CostEstimateAndPlateSelectionTests(TestCase):
    setUpTestData = classmethod(correction_tests.CompletedOrderCorrectionTests.setUpTestData.__func__)
    setUp = correction_tests.CompletedOrderCorrectionTests.setUp
    order = correction_tests.CompletedOrderCorrectionTests.order
    payload = correction_tests.CompletedOrderCorrectionTests.payload
    post = correction_tests.CompletedOrderCorrectionTests.post
    assert_saved = correction_tests.CompletedOrderCorrectionTests.assert_saved

    def pending(self, **overrides):
        data = dict(status=SalesOrder.Status.ALLOCATION_PENDING, registration_date=None, order_date=date(2026, 9, 10),
                    actual_balance=70000, plate_insurance_fee=0, registration_plate_fee=0, registration_calculated_total=0)
        data.update(overrides)
        return self.order(**data)

    def test_cost_is_estimated_by_order_date_then_follows_registration_date(self):
        VehicleSettlementCostRule.objects.create(vehicle_model=self.model, amount=Decimal("60000"), effective_from=date(2026, 9, 1))
        later = VehicleSettlementCostRule.objects.create(vehicle_model=self.model, amount=Decimal("61000"), effective_from=date(2026, 10, 1))
        order = self.pending()
        sync_order_operations(order.pk)
        profile = OrderOperationsProfile.objects.get(order=order)
        self.assertEqual(profile.vehicle_cost, Decimal("60000"), "領牌前依訂單日預估")
        self.assertIsNone(profile.vehicle_cost_locked_at)
        order.registration_date = date(2026, 10, 5)
        order.save(update_fields=["registration_date", "updated_at"])
        profile = apply_order_settlement_cost(order, "tester", lock=True)
        self.assertEqual(profile.vehicle_cost, Decimal("61000"), "領牌後依領牌日重新帶入")
        self.assertEqual(profile.vehicle_cost_rule, later)
        self.assertIsNotNone(profile.vehicle_cost_locked_at)

    def test_estimate_without_rule_keeps_existing_cost(self):
        order = self.pending()
        profile, _ = OrderOperationsProfile.objects.get_or_create(order=order)
        OrderOperationsProfile.objects.filter(pk=profile.pk).update(vehicle_cost=Decimal("55555"))
        sync_order_operations(order.pk)
        self.assertEqual(OrderOperationsProfile.objects.get(pk=profile.pk).vehicle_cost, Decimal("55555"))

    def test_plate_selection_fee_counts_before_registration_date(self):
        order = self.pending(plate_choice="watch")
        response = self.post(order, plate_choice="watch", plate_selection_fee="1200", plate_insurance_fee="",
                             registration_date="", confirm_completed_correction="")
        self.assert_saved(response, order)
        self.assertEqual(order.plate_selection_fee, Decimal("1200"))
        self.assertEqual(order.plate_insurance_fee, Decimal("1200"))
        self.assertEqual(order.calculate_balance(), Decimal("71200"))
        profile = OrderOperationsProfile.objects.get(order=order)
        self.assertEqual(profile.plate_selection_income, Decimal("1200"))
        self.assertEqual(profile.plate_selection_expense, Decimal("1200"))
        page = self.client.get(f"/orders/{order.pk}/edit/")
        self.assertContains(page, 'data-conditional="plate-selection"')

    def test_installment_customer_balance_includes_plate_selection(self):
        order = self.pending(payment_type="installment", installment_company="測試分期", installment_periods=24,
                             installment_monthly=Decimal("2917"), installment_amount=70000, cash_receivable_v2=True,
                             plate_selection_fee=1200, plate_insurance_fee=1200, registration_calculated_total=1200,
                             actual_balance=71200)
        self.assertEqual(default_customer_balance(order), Decimal("1200"))

    def test_migration_moves_plate_selection_other_fee(self):
        order = self.pending(plate_choice="watch")
        OtherFeeLine.objects.create(order=order, name="選號", amount=1200)
        before_total = SalesOrder.objects.get(pk=order.pk).calculate_balance()
        import_module("sales.migrations.0174_move_plate_selection_other_fee").move(django_apps, None)
        order = SalesOrder.objects.get(pk=order.pk)
        self.assertEqual(order.plate_selection_fee, Decimal("1200"))
        self.assertEqual(order.plate_insurance_fee, Decimal("1200"))
        self.assertFalse(order.other_fees.exists())
        self.assertEqual(order.calculate_balance(), before_total, "客人應付總額不變")
        self.assertTrue(order.events.filter(actor_name__contains="選號費搬移").exists())
