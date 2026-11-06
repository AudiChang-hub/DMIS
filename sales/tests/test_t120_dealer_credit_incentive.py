"""T-120（使用者 2026-11-06 選 A）：
p16 車行現金單的掛帳應收＝車行結算「向車行收」（扣傭金），收清判斷同一個金額；分期車行單照舊。
p13 領牌前手動填的獎勵，找到車型版本後與版本金額相同的改回系統帶入，不同的照舊保留。"""
from datetime import date
from decimal import Decimal

from sales.models import OrderOperationsProfile, PaymentRecord, SalesOrder, VehicleIncentiveRule
from sales.services.customer_receivable import dealer_cash_credit
from sales.services.dealer_commission import apply_order_dealer_commission
from sales.services.dealer_settlement import dealer_settlement
from sales.services.incentive_rule import apply_order_incentive_rule
from sales.services.operations_sync import sync_order_operations
from sales.services.order_workspace import receipt_status
from sales.services.payment_summary import payment_summary
from sales.tests import test_finance_ledger as ledger


class DealerCashCreditTests(ledger.FinanceLedgerTestBase):
    def dealer_order(self, **kwargs):
        order = self.make_order(cash_receivable_v2=True, **kwargs)
        apply_order_dealer_commission(order)
        sync_order_operations(order.pk)
        return SalesOrder.objects.get(pk=order.pk)

    def test_cash_dealer_credit_equals_settlement(self):
        order = self.dealer_order()
        settlement = dealer_settlement(order)
        self.assertEqual(settlement["label"], "向車行收")
        commission = self.profile(order).dealer_commission_expense
        self.assertGreater(commission, 0)
        self.assertEqual(dealer_cash_credit(order), settlement["total"])
        self.assertEqual(settlement["total"], order.vehicle_price - commission + order.plate_insurance_fee)
        summary = payment_summary(order)
        self.assertEqual(summary["customer_expected"], settlement["total"])
        self.assertEqual(PaymentRecord.objects.get(order=order, system_key="balance").expected_amount, settlement["total"])
        texts = [item["text"] for item in receipt_status(order, summary)["items"]]
        self.assertIn(f"車行掛帳（已扣傭金）還差 {settlement['total']:,.0f} 元", texts)
        PaymentRecord.objects.create(order=order, item_name="車行付款", expected_amount=0, received_amount=settlement["total"],
                                     received_on=date(2026, 9, 20), payment_method="匯款", confirmed=True)
        self.assertTrue(payment_summary(SalesOrder.objects.get(pk=order.pk))["settled"])

    def test_commission_change_resyncs_unpaid_balance_row(self):
        order = self.dealer_order()
        before = PaymentRecord.objects.get(order=order, system_key="balance").expected_amount
        self.model.base_dealer_commission = Decimal("2500")
        self.model.save(update_fields=["base_dealer_commission"])
        apply_order_dealer_commission(SalesOrder.objects.get(pk=order.pk))
        after = PaymentRecord.objects.get(order=order, system_key="balance").expected_amount
        self.assertEqual(before - after, Decimal("500"))

    def test_installment_dealer_and_store_orders_are_unchanged(self):
        installment = self.make_order(cash_receivable_v2=True, payment_type="installment", installment_amount=Decimal("60000"),
                                      installment_company="測試分期", installment_periods=24,
                                      payment_splits=[{"method": "cash", "amount": 19800}, {"method": "installment", "amount": 60000}])
        self.assertIsNone(dealer_cash_credit(installment))
        store = self.make_order(cash_receivable_v2=True, source_type="store", source=self.staff)
        self.assertIsNone(dealer_cash_credit(store))


class IncentiveManualReleaseTests(ledger.FinanceLedgerTestBase):
    def test_manual_value_equal_to_rule_returns_to_system(self):
        VehicleIncentiveRule.objects.create(vehicle_model=self.model, effective_from=date(2026, 8, 1),
                                            sales_bonus=2000, promotion_subsidy=1500)
        order = self.make_order(source_type="platform", source=self.platform, registration_date=date(2026, 9, 10))
        profile, _created = OrderOperationsProfile.objects.get_or_create(order=order)
        OrderOperationsProfile.objects.filter(pk=profile.pk).update(
            sales_bonus=2000, promotion_subsidy=1200, manual_financial_fields=["promotion_subsidy", "sales_bonus", "vehicle_cost"])
        profile = apply_order_incentive_rule(SalesOrder.objects.get(pk=order.pk))
        profile.refresh_from_db()
        self.assertEqual((profile.sales_bonus, profile.promotion_subsidy), (2000, 1200))
        self.assertEqual(profile.manual_financial_fields, ["promotion_subsidy", "vehicle_cost"])
