"""T-285 A 案（使用者 2026-11-23）：分期額外撥款獎金隨車價收入計入淨利，公式不變、不重複列入獎勵與補助。

收支「車價收入」那列依本單分期快照的獎金加註「含分期公司額外撥款獎金 N 元」；快照是 0 的單不顯示。
"""
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from sales.forms import InstallmentPlanOptionForm
from sales.models import (
    InstallmentCompany, InstallmentPlanOption, InstallmentPlanVersion, OrderOperationsProfile, SalesOrder,
)
from sales.services.finance_ledger import _order_overrides
from sales.services.installment_plan import apply_order_installment_snapshot
from sales.services.operations_sync import sync_order_operations
from sales.tests.test_finance_ledger import FinanceLedgerTestBase

NOTE = "含分期公司額外撥款獎金"


class InstallmentBonusProfitTests(FinanceLedgerTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        company = InstallmentCompany.objects.create(name="和潤")
        version = InstallmentPlanVersion.objects.create(
            vehicle_model=cls.model, effective_from=timezone.localdate() - timedelta(days=30))
        common = dict(version=version, company=company, opening_fee=0, expected_disbursement_method="rate",
                      expected_disbursement_rate=Decimal("96"))
        # 24 期有 300 元獎金、18 期沒有；其他條件相同，兩張單只差獎金。
        InstallmentPlanOption.objects.create(periods=24, monthly_amount=3000, extra_disbursement_bonus=300, **common)
        InstallmentPlanOption.objects.create(periods=18, monthly_amount=4000, extra_disbursement_bonus=0, **common)

    def installment_order(self, periods, monthly, **kwargs):
        fields = dict(source_type="store", source=self.staff, payment_type="installment", installment_company="和潤",
                      installment_periods=periods, installment_monthly=Decimal(monthly), order_date=timezone.localdate())
        fields.update(kwargs)
        order = self.make_order(**fields)
        apply_order_installment_snapshot(order)
        sync_order_operations(order.pk)
        return SalesOrder.objects.get(pk=order.pk)

    def hint(self, order):
        return _order_overrides(OrderOperationsProfile.objects.get(order=order))[1].get("actual_disbursement", "")

    def test_bonus_is_in_vehicle_revenue_and_net_profit_exactly_once(self):
        with_bonus = self.installment_order(24, "3000")
        without = self.installment_order(18, "4000")
        self.assertEqual(with_bonus.installment_plan_snapshot["extra_disbursement_bonus"], 300)
        base = (Decimal("79800") * Decimal("96") / Decimal("100")).quantize(Decimal("1"))
        bonus_profile, plain_profile = self.profile(with_bonus), self.profile(without)
        self.assertEqual(bonus_profile.actual_disbursement, base + 300, "獎金含在車價收入")
        self.assertEqual(plain_profile.actual_disbursement, base)
        self.assertEqual(bonus_profile.net_profit - plain_profile.net_profit, Decimal("300"), "淨利只多 300，不重複")
        for name in OrderOperationsProfile.INCENTIVE_FIELDS:
            self.assertEqual(getattr(bonus_profile, name), getattr(plain_profile, name), f"獎勵與補助 {name} 不含獎金")

    def test_vehicle_revenue_row_notes_the_snapshot_bonus(self):
        order = self.installment_order(24, "3000")
        self.assertIn(f"{NOTE} 300 元", self.hint(order))
        self.assertIn("分期那筆×撥款比例", self.hint(order), "保留原本的預估說明")
        self.client.force_login(self.admin)
        page = self.client.get(reverse("order_operations", args=[order.pk]))
        self.assertContains(page, f"{NOTE} 300 元")

    def test_note_uses_this_orders_snapshot_amount(self):
        order = self.installment_order(24, "3000")
        snapshot = {**order.installment_plan_snapshot, "extra_disbursement_bonus": 1200}
        SalesOrder.objects.filter(pk=order.pk).update(installment_plan_snapshot=snapshot)
        self.assertIn(f"{NOTE} 1,200 元", self.hint(order))

    def test_snapshot_without_bonus_shows_no_note_even_if_plan_has_one_now(self):
        # 像 SO20261010-167D11：建單時方案沒有獎金，之後方案才加上；以本單快照為準。
        order = self.installment_order(24, "3000")
        snapshot = {**order.installment_plan_snapshot, "extra_disbursement_bonus": 0}
        SalesOrder.objects.filter(pk=order.pk).update(installment_plan_snapshot=snapshot)
        self.assertNotIn(NOTE, self.hint(order))

    def test_no_note_for_plans_without_bonus_or_cash_orders(self):
        self.assertNotIn(NOTE, self.hint(self.installment_order(18, "4000")))
        self.assertNotIn(NOTE, self.hint(self.make_order(source_type="store", source=self.staff)))

    def test_note_stays_after_reconciliation_posting(self):
        order = self.installment_order(24, "3000")
        OrderOperationsProfile.objects.filter(order=order).update(payment_disbursement_snapshot={"applied": "76909"})
        hint = self.hint(order)
        self.assertIn("已在統一撥款對帳入帳", hint)
        self.assertIn(f"{NOTE} 300 元", hint)

    def test_plan_form_help_text_says_bonus_counts_toward_net_profit(self):
        text = str(InstallmentPlanOptionForm().fields["extra_disbursement_bonus"].help_text)
        self.assertIn("會隨車價收入計入淨利，不要再填到獎勵與補助", text)
        self.assertNotIn("不會再重複列入淨利獎勵", text)
