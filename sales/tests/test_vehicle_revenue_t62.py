"""實際車價收入（使用者 2026-10-21 T-62）。

收入的「實際撥款」改稱「實際車價收入」：預設＝訂單車價，其中分期那筆×撥款比例，現金／刷卡／匯款全額。
撥款比例沿用車型方案；自訂分期沒有方案時用同期數的方案比例。統一撥款對帳入帳只改寫分期那部分。
人工調整過的值不動。
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from sales.models import InstallmentCompany, InstallmentPlanOption, InstallmentPlanVersion, OrderOperationsProfile, VehicleModel
from sales.services.finance_ledger import LABELS
from sales.services.financial_audit import audit_financial_consistency
from sales.services.financial_refresh import refresh_unlocked_financials
from sales.services.incentive_rule import _calculated_disbursement
from sales.services.installment_plan import apply_order_installment_snapshot
from sales.services.operations_sync import sync_payment_financials
from sales.services.order_return import lender_disbursed
from sales.services.payment_ledger import ledger_totals
from sales.tests import test_payment_splits as split_tests

splits = split_tests.splits

MIXED = splits(("installment", 30000), ("cash", 30000), ("card", 19800))


class VehicleRevenueTests(TestCase):
    setUp = split_tests.PaymentSplitTests.setUp
    image = split_tests.PaymentSplitTests.image
    complete_data = split_tests.PaymentSplitTests.complete_data
    submit = split_tests.PaymentSplitTests.submit
    create = split_tests.PaymentSplitTests.create

    def plan(self, periods=24, rate="96", company="和潤", model=None):
        company, _ = InstallmentCompany.objects.get_or_create(name=company)
        version, _ = InstallmentPlanVersion.objects.get_or_create(
            vehicle_model=model or self.model, effective_from=timezone.localdate() - timedelta(days=30))
        return InstallmentPlanOption.objects.create(
            version=version, company=company, periods=periods, monthly_amount=3000, opening_fee=0,
            expected_disbursement_method="rate", expected_disbursement_rate=Decimal(rate))

    def other_model(self, number):
        return VehicleModel.objects.create(brand="SUZUKI", name=f"其他車 {number}", model_number=f"X{number}", model_year=2026)

    def ops(self, order):
        return OrderOperationsProfile.objects.get(order=order)

    def mixed_order(self, **changes):
        self.plan()
        return self.create(payment_splits=MIXED, installment_company="和潤", installment_periods="24", installment_monthly="3000", **changes)

    def test_mixed_installment_revenue_is_installment_part_times_rate_plus_customer_parts(self):
        order = self.mixed_order()
        self.assertEqual(order.installment_plan_snapshot["expected_disbursement_amount"], 28800)
        self.assertEqual(_calculated_disbursement(order), Decimal("78600"))
        refresh_unlocked_financials(order.pk)
        self.assertEqual(self.ops(order).actual_disbursement, Decimal("78600"))
        # 分期公司撥款的應收仍只算分期那部分。
        self.assertEqual(order.payment_records.get(system_key="installment_disbursement").expected_amount, Decimal("28800"))

    def test_single_installment_and_cash_orders_are_unchanged(self):
        self.plan()
        order = self.create(payment_splits=splits(("installment", 79800)), installment_company="和潤", installment_periods="24", installment_monthly="3000")
        self.assertEqual(_calculated_disbursement(order), Decimal("76608"))
        cash = self.create(payment_splits=splits(("cash", 79800)))
        self.assertEqual(_calculated_disbursement(cash), Decimal("79800"))

    def test_custom_installment_borrows_same_period_rate(self):
        self.plan(model=self.other_model(1))
        order = self.create(payment_splits=MIXED, installment_custom="on", installment_company="其他融資", installment_periods="24", installment_monthly="1250")
        snapshot = order.installment_plan_snapshot
        self.assertEqual((snapshot["expected_disbursement_method"], snapshot["expected_disbursement_rate"]), ("manual", "96.00"))
        self.assertEqual(snapshot["expected_disbursement_amount"], 28800)
        self.assertEqual(snapshot["expected_disbursement_method_label"], "沿用同期數方案撥款 96%")
        self.assertEqual(_calculated_disbursement(order), Decimal("78600"))

    def test_custom_installment_without_a_unique_rate_stays_manual(self):
        self.plan(periods=42, rate="90", company="甲", model=self.other_model(1))
        self.plan(periods=42, rate="91", company="乙", model=self.other_model(2))
        order = self.create(payment_splits=MIXED, installment_custom="on", installment_company="丙", installment_periods="42", installment_monthly="1000")
        self.assertIsNone(order.installment_plan_snapshot["expected_disbursement_amount"])
        self.assertEqual(order.installment_plan_snapshot["expected_disbursement_method_label"], "本單另填")
        self.assertIsNone(_calculated_disbursement(order))
        # 同分期公司只有一種比例時採用。
        order.installment_company = "乙"
        apply_order_installment_snapshot(order)
        self.assertEqual(order.installment_plan_snapshot["expected_disbursement_rate"], "91.00")

    def test_reconciliation_rewrites_only_the_lender_part(self):
        order = self.mixed_order()
        refresh_unlocked_financials(order.pk)
        lender = order.payment_records.get(system_key="installment_disbursement")
        lender.received_amount = Decimal("28000")
        lender.received_on = timezone.localdate()
        lender.confirmed = True
        lender.save()
        sync_payment_financials(order.pk, adopt_payment_id=lender.pk)
        profile = self.ops(order)
        self.assertEqual(profile.actual_disbursement, Decimal("28000") + Decimal("49800"))
        self.assertNotIn("confirmed_disbursement_mismatch", audit_financial_consistency()["finding_counts"])
        # 退車時分期公司已撥款只算分期那部分。
        order.refresh_from_db()
        self.assertEqual(lender_disbursed(order, ledger_totals(order), profile), Decimal("28000"))
        # 取消入帳（勾錯取消「已確認」後清掉實收）後還原入帳前的值。
        lender.confirmed = False
        lender.save()
        lender.received_amount = 0
        lender.save()
        self.assertEqual(self.ops(order).actual_disbursement, Decimal("78600"))

    def test_manual_value_is_kept(self):
        order = self.mixed_order()
        OrderOperationsProfile.objects.filter(order=order).update(actual_disbursement=70000, manual_financial_fields=["actual_disbursement"])
        refresh_unlocked_financials(order.pk)
        self.assertEqual(self.ops(order).actual_disbursement, Decimal("70000"))

    def test_ledger_label(self):
        self.assertEqual(LABELS["actual_disbursement"], "實際車價收入")
