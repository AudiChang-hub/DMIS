"""統一撥款對帳（使用者 2026-10-22 T-96）。

分期、網路平台都是事後才撥款，要對帳（車行來源的分期單只對分期公司撥款）；現金、刷卡、匯款、客人另付的款項與 Excel 匯入單不對帳。
分期撥款預計＝分期金額×撥款比例；平台撥款不比預計、只記實際，可多張一起入帳。差額入帳後才算。
確認日期按入帳當天自動記錄。訂單收支入帳前稱「預估車價收入」，入帳後改回「實際車價收入」並鎖定。
"""
import importlib
from datetime import timedelta
from decimal import Decimal

from django.apps import apps
from django.urls import reverse
from django.utils import timezone

from sales.models import (
    InstallmentCompany, InstallmentPlanOption, InstallmentPlanVersion, LegacyImportBatch, LegacyImportRow,
    LegacySalesSnapshot, OrderEvent, OrderOperationsProfile, PaymentRecord, SalesOrder,
)
from sales.services.finance_ledger import _order_overrides
from sales.services.installment_plan import apply_order_installment_snapshot
from sales.services.order_next_actions import _pending_reconciliation_action
from sales.services.operations_sync import sync_order_operations
from sales.services.payment_summary import payment_summary
from sales.tests.test_finance_ledger import FinanceLedgerTestBase

migration = importlib.import_module("sales.migrations.0196_platform_payout_rows")


class PayoutReconciliationTests(FinanceLedgerTestBase):
    def setUp(self):
        self.client.force_login(self.admin)

    def platform_order(self, **kwargs):
        fields = dict(source_type="platform", source=self.platform, vehicle_price=Decimal("0"), plate_insurance_fee=Decimal("2100"))
        fields.update(kwargs)
        return self.make_order(**fields)

    def installment_order(self, rate="96", **kwargs):
        company, _ = InstallmentCompany.objects.get_or_create(name="和潤")
        version, _ = InstallmentPlanVersion.objects.get_or_create(
            vehicle_model=self.model, effective_from=timezone.localdate() - timedelta(days=30))
        InstallmentPlanOption.objects.get_or_create(
            version=version, company=company, periods=24,
            defaults=dict(monthly_amount=3000, opening_fee=0, expected_disbursement_method="rate",
                          expected_disbursement_rate=Decimal(rate)))
        fields = dict(source_type="store", source=self.staff, payment_type="installment", installment_company="和潤",
                      installment_periods=24, installment_monthly=Decimal("3000"), order_date=timezone.localdate())
        fields.update(kwargs)
        order = self.make_order(**fields)
        apply_order_installment_snapshot(order)
        sync_order_operations(order.pk)
        return SalesOrder.objects.get(pk=order.pk)

    def payout(self, order):
        return order.payment_records.get(system_key__in=PaymentRecord.PAYOUT_KEYS)

    def listed(self, **params):
        response = self.client.get(reverse("reconciliation_list"), params)
        self.assertEqual(response.status_code, 200)
        return response, {record.pk for record in response.context["records"]}

    def post(self, record, amount, **extra):
        return self.client.post(reverse("reconciliation_update", args=[record.pk]), {
            "received_amount": amount, "expected_amount": int(record.expected_amount), "note": "", **extra,
        })

    def test_platform_order_gets_a_payout_row_outside_customer_receivables(self):
        order = self.platform_order()
        row = self.payout(order)
        self.assertEqual((row.item_name, row.effective_receipt_kind, row.expected_amount), ("平台撥款", "lender", 0))
        self.assertEqual(row.receipt_kind_label, "平台撥款")
        self.assertTrue(row.is_receivable_only, "未入帳的平台撥款不列在訂單收款明細")
        summary = payment_summary(order)
        self.assertEqual((summary["customer_expected"], summary["lender_expected"]), (Decimal("2100"), Decimal("0")))

    def test_scope_lists_only_system_installment_and_platform_payouts(self):
        platform = self.platform_order()
        installment = self.installment_order()
        cash = self.make_order(source_type="store", source=self.staff)
        dealer_installment = self.installment_order(source_type="dealer", source=self.dealer)
        legacy = self.installment_order()
        batch = LegacyImportBatch.objects.create(import_type="operations", original_filename="synthetic.xlsx", file_size=0)
        LegacySalesSnapshot.objects.create(order=legacy, import_row=LegacyImportRow.objects.create(
            batch=batch, sheet_name="銷貨", source_row=1, fingerprint="t96-legacy"))
        dealer_cash = self.make_order()
        _response, ids = self.listed()
        self.assertEqual(ids, {self.payout(platform).pk, self.payout(installment).pk, self.payout(dealer_installment).pk})
        for order in (cash, dealer_cash, legacy):
            self.assertFalse(order.payment_records.filter(pk__in=ids).exists(), order.number)
        self.assertFalse(dealer_installment.payment_records.exclude(system_key="installment_disbursement").filter(pk__in=ids).exists(),
                         "車行分期單只對分期公司撥款那一列")
        self.assertFalse(platform.payment_records.filter(system_key__in=["deposit", "balance"], pk__in=ids).exists())
        self.assertEqual(self.listed(channel="platform")[1], {self.payout(platform).pk})
        self.assertEqual(self.listed(channel="installment")[1], {self.payout(installment).pk, self.payout(dealer_installment).pk})

    def test_installment_expected_is_split_times_rate_and_difference_waits_for_posting(self):
        order = self.installment_order()
        row = self.payout(order)
        self.assertEqual(row.expected_amount, Decimal("76608"))
        response, _ids = self.listed()
        self.assertContains(response, "待入帳")
        self.assertContains(response, 'data-expected="76608"')
        self.assertContains(response, "按入帳自動記")
        self.assertNotContains(response, 'name="received_on"')
        self.assertNotContains(response, "difference-warning")

        self.post(row, 76000)
        row.refresh_from_db()
        self.assertTrue(row.confirmed)
        self.assertEqual(row.received_on, timezone.localdate(), "確認日期自動記為入帳當天")
        response, _ids = self.listed()
        self.assertContains(response, "difference-warning")
        self.assertContains(response, "$-608")
        profile = OrderOperationsProfile.objects.get(order=order)
        self.assertEqual(profile.actual_disbursement, Decimal("76000"))
        self.assertEqual(profile.card_fee_expense, Decimal("0"), "差額不自動記成手續費")

    def test_platform_prefills_estimate_and_posting_locks_the_revenue(self):
        order = self.platform_order()
        OrderOperationsProfile.objects.filter(order=order).update(
            actual_disbursement=61277, manual_financial_fields=["actual_disbursement"])
        row = self.payout(order)
        profile = OrderOperationsProfile.objects.get(order=order)
        self.assertEqual(_order_overrides(profile)[0]["actual_disbursement"], "預估車價收入")
        response, _ids = self.listed()
        self.assertContains(response, 'value="61277"')
        self.assertContains(response, "平台撥款不比預計")
        self.assertContains(response, "已帶入收支的預估撥款")
        row.refresh_from_db()
        self.assertEqual((row.received_amount, row.confirmed), (0, False), "預填只在畫面上，不先寫入")

        self.post(row, 61000)
        profile.refresh_from_db()
        self.assertEqual(profile.actual_disbursement, Decimal("61000"))
        self.assertNotIn("actual_disbursement", _order_overrides(profile)[0], "入帳後改回實際車價收入")
        page = self.client.get(reverse("order_operations", args=[order.pk]))
        self.assertTrue(page.context["form"].fields["actual_disbursement"].disabled)

    def test_unconfirm_on_reconciliation_page_restores_the_estimate(self):
        order = self.platform_order()
        OrderOperationsProfile.objects.filter(order=order).update(
            actual_disbursement=61277, manual_financial_fields=["actual_disbursement"])
        row = self.payout(order)
        self.post(row, 61000)
        response = self.client.post(reverse("reconciliation_unconfirm", args=[row.pk]), follow=True)
        self.assertContains(response, "已取消")
        row.refresh_from_db()
        self.assertFalse(row.confirmed)
        profile = OrderOperationsProfile.objects.get(order=order)
        self.assertEqual(profile.actual_disbursement, Decimal("61277"))
        self.assertEqual(_order_overrides(profile)[0]["actual_disbursement"], "預估車價收入")
        self.assertTrue(OrderEvent.objects.filter(order=order, description__contains="取消平台撥款入帳").exists())

    def test_batch_posts_several_platform_orders_together(self):
        first, second = self.platform_order(), self.platform_order()
        rows = [self.payout(first), self.payout(second)]
        response = self.client.post(reverse("reconciliation_batch"), {
            "records": [row.pk for row in rows], f"amount_{rows[0].pk}": "61000", f"amount_{rows[1].pk}": "59000",
        }, follow=True)
        self.assertContains(response, "已合併入帳 2 筆平台撥款，合計 120,000 元")
        for row, amount in zip(rows, (61000, 59000)):
            row.refresh_from_db()
            self.assertEqual((row.confirmed, row.received_amount, row.received_on), (True, amount, timezone.localdate()))
            self.assertEqual(OrderOperationsProfile.objects.get(order=row.order).actual_disbursement, amount)
        self.assertTrue(OrderEvent.objects.filter(order=first, description__contains="合併入帳").exists())

    def test_batch_is_all_or_nothing(self):
        first, second = self.platform_order(), self.platform_order()
        rows = [self.payout(first), self.payout(second)]
        response = self.client.post(reverse("reconciliation_batch"), {
            "records": [row.pk for row in rows], f"amount_{rows[0].pk}": "61000", f"amount_{rows[1].pk}": "",
        }, follow=True)
        self.assertContains(response, "合併入帳沒有完成")
        for row in rows:
            row.refresh_from_db()
            self.assertFalse(row.confirmed)
        installment = self.payout(self.installment_order())
        response = self.client.post(reverse("reconciliation_batch"), {
            "records": [installment.pk], f"amount_{installment.pk}": "70000"}, follow=True)
        self.assertContains(response, "不是平台撥款")

    def test_out_of_scope_rows_cannot_be_posted(self):
        order = self.platform_order()
        balance = order.payment_records.get(system_key="deposit")
        response = self.post(balance, 2100)
        self.assertEqual(response.status_code, 302)
        balance.refresh_from_db()
        self.assertEqual(balance.received_amount, Decimal("0"))

    def test_estimate_label_only_for_reconciled_orders(self):
        for order in (self.installment_order(), self.installment_order(source_type="dealer", source=self.dealer)):
            profile = OrderOperationsProfile.objects.get(order=order)
            self.assertEqual(_order_overrides(profile)[0]["actual_disbursement"], "預估車價收入")
        for order in (self.make_order(source_type="store", source=self.staff), self.make_order()):
            self.assertNotIn("actual_disbursement", _order_overrides(OrderOperationsProfile.objects.get(order=order))[0])

    def test_next_action_points_platform_orders_to_reconciliation(self):
        today = timezone.localdate()
        action = _pending_reconciliation_action(self.platform_order(), today)
        self.assertEqual(action.title, "登記平台撥款")
        self.assertIsNone(_pending_reconciliation_action(self.make_order(), today), "車行現金單不提醒撥款對帳")

    def test_migration_adds_rows_only_for_system_platform_orders_and_reverses(self):
        order = self.platform_order()
        PaymentRecord.objects.filter(order=order, system_key="platform_disbursement").delete()
        migration.add_platform_rows(apps, None)
        migration.add_platform_rows(apps, None)
        self.assertEqual(order.payment_records.filter(system_key="platform_disbursement").count(), 1)
        migration.remove_empty_platform_rows(apps, None)
        self.assertFalse(order.payment_records.filter(system_key="platform_disbursement").exists())

    def test_migration_refreshes_stale_custom_installment_estimate(self):
        order = self.installment_order()
        stale = {**order.installment_plan_snapshot, "expected_disbursement_method": "manual",
                 "expected_disbursement_amount": None, "base_expected_disbursement_amount": None}
        SalesOrder.objects.filter(pk=order.pk).update(installment_plan_snapshot=stale, installment_custom=True)
        PaymentRecord.objects.filter(order=order, system_key="installment_disbursement").update(expected_amount=0)
        migration.refresh_stale_installment_estimates(apps, None)
        self.assertEqual(self.payout(order).expected_amount, Decimal("76608"))
