"""UAT p4（使用者 2026-11-06 選 A）：規費、強制險支出一律由本店付、照試算帶入，分期公司不負擔牌險；
收入看客人付的牌險費，填 0＝本店自己出。取代 10-19「分期單牌險 0 由分期公司吸收」。"""
from io import StringIO

from django.core.management import call_command

from sales.models import OrderOperationsProfile, SalesOrder
from sales.services.finance_ledger import _order_overrides
from sales.tests import test_finance_ledger as ledger


class InstallmentPlateCostTests(ledger.FinanceLedgerTestBase):
    COST_2100 = ledger.AgencyFeeTests.COST_2100
    INSTALLMENT = ledger.AgencyFeeTests.INSTALLMENT
    synced = ledger.AgencyFeeTests.synced
    plate_case = ledger.AgencyFeeTests.plate_case

    def old_rule(self, order):
        """模擬改版前的資料：分期單牌險 0 時規費、強制險支出記 0。"""
        OrderOperationsProfile.objects.filter(order=order).update(registration_tax_expense=0, compulsory_insurance_expense=0)

    def test_installment_waived_plate_lists_store_paid_costs_like_cash(self):
        _order, cash, _balance = self.plate_case(plate_insurance_fee=0)
        _order, installment, _balance = self.plate_case(plate_insurance_fee=0, **self.INSTALLMENT)
        for name in ("registration_tax_expense", "compulsory_insurance_expense", "registration_tax_income",
                     "compulsory_insurance_income", "agency_fee_income"):
            self.assertEqual(getattr(installment, name), getattr(cash, name), name)
        self.assertEqual((installment.registration_tax_expense, installment.compulsory_insurance_expense), (1100, 1000))
        labels, hints = _order_overrides(installment)
        self.assertEqual(hints["registration_tax_income"], "牌險費 0：沒有向客人收，支出由店家吸收")
        self.assertNotIn("分期公司吸收", " ".join(hints.values()))

    def test_open_orders_follow_new_rule_on_next_sync_but_completed_and_cancelled_do_not(self):
        open_order, _profile, _balance = self.plate_case(plate_insurance_fee=0, **self.INSTALLMENT)
        done, _profile, _balance = self.plate_case(plate_insurance_fee=0, **self.INSTALLMENT)
        cancelled, _profile, _balance = self.plate_case(plate_insurance_fee=0, **self.INSTALLMENT)
        for order in (open_order, done, cancelled):
            self.old_rule(order)
        SalesOrder.objects.filter(pk=done.pk).update(status=SalesOrder.Status.COMPLETED)
        SalesOrder.objects.filter(pk=cancelled.pk).update(status=SalesOrder.Status.CANCELLED)
        self.assertEqual(self.synced(open_order).registration_tax_expense, 1100)
        self.assertEqual(self.synced(done).registration_tax_expense, 0, "已完成訂單不回填")
        self.assertEqual(self.synced(cancelled).registration_tax_expense, 0, "已取消訂單不重算")

    def test_preview_command_lists_changes_without_writing(self):
        open_order, _profile, _balance = self.plate_case(plate_insurance_fee=0, **self.INSTALLMENT)
        done, _profile, _balance = self.plate_case(plate_insurance_fee=0, **self.INSTALLMENT)
        manual, _profile, _balance = self.plate_case(plate_insurance_fee=0, **self.INSTALLMENT)
        cancelled, _profile, _balance = self.plate_case(plate_insurance_fee=0, **self.INSTALLMENT)
        cash, _profile, _balance = self.plate_case(plate_insurance_fee=0)
        for order in (open_order, done, manual, cancelled, cash):
            self.old_rule(order)
        OrderOperationsProfile.objects.filter(order=manual).update(
            manual_financial_fields=["registration_tax_expense", "compulsory_insurance_expense"])
        SalesOrder.objects.filter(pk=done.pk).update(status=SalesOrder.Status.COMPLETED)
        SalesOrder.objects.filter(pk=cancelled.pk).update(status=SalesOrder.Status.CANCELLED)
        out = StringIO()
        call_command("preview_installment_plate_costs", stdout=out)
        text = out.getvalue()
        self.assertIn("符合：2 張", text)
        self.assertIn(f"{open_order.number}（", text)
        self.assertIn(f"{done.number}（", text)
        self.assertIn("規費支出 0→1,100；強制險支出 0→1,000｜淨利 -2,100", text)
        self.assertIn("已完成（不回填，只列出）：1 張，淨利合計變化 -2,100", text)
        for skipped in (manual, cancelled, cash):
            self.assertNotIn(skipped.number, text)
        self.assertIn("dry-run", text)
        # 只列出，不寫入。
        self.assertEqual(self.profile(open_order).registration_tax_expense, 0)
        self.assertEqual(self.profile(done).registration_tax_expense, 0)
