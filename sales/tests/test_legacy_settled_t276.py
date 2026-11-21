"""T-276（使用者 2026-11-21 選 B）：Excel 匯入單＝已人工處理完的歷史資料，款項、補助一律算已完成。

- 收款：payment_summary 的 settled 對已離開進行中狀態的匯入單一律為 True，訂單頁收款狀態卡、全部訂單
  「收款確認」篩選、報表明細「收款確認」欄、存檔重算（payment_confirmation_changes）都跟著算已收清；
  應收、尾款、legacy_settled 與統計不變。進行中的匯入單仍依實收判斷。
- 補助：匯入單不追蹤補助缺件（_subsidy_action、_subsidy_step、訂單頁 subsidy_missing），不預設打開補助分頁。
- 訂單匯出：「確認收款」「分期公司確認匯款」匯入單輸出「是」。
- 「Excel 匯入已修改」（匯入後有人改過，order_origin）比照匯入單；金額用人員改過的值，系統不重算、不覆蓋。
每一項都配一張同條件的系統單，證明系統單行為不變。
"""
from decimal import Decimal

from django.urls import reverse

from sales.models import (LegacyImportBatch, LegacyImportRow, LegacySalesSnapshot, OrderEvent, OrderOperationsProfile,
                          PaymentRecord, SalesOrder, payment_ledger_maintenance)
from sales.order_exchange.columns import COLUMN_BY_KEY
from sales.reporting.records import record_cells, record_queryset
from sales.services.financial_audit import audit_financial_consistency
from sales.services.operations_sync import payment_confirmation_changes
from sales.services.order_filters import filter_order_analysis
from sales.services.operations_sync import sync_order_operations
from sales.services.order_next_actions import build_order_next_actions
from sales.services.order_origin import IMPORTED_EDITED, current_order_origin
from sales.services.order_steps import _subsidy_step
from sales.services.order_workspace import receipt_status
from sales.services.payment_summary import payment_summary
from sales.tests.test_finance_ledger import FinanceLedgerTestBase

UNCHANGED_KEYS = ("customer_expected", "lender_expected", "customer_due", "lender_due", "delivery_due",
                  "legacy_settled", "customer_overpaid", "unconfirmed_received")


class LegacySettledTests(FinanceLedgerTestBase):
    def setUp(self):
        self.batch = LegacyImportBatch.objects.create(import_type="operations", original_filename="synthetic.xlsx",
                                                      file_size=0)

    def order(self, legacy, *, status="completed", receipt=None, confirmed=None, **kwargs):
        """正式站常見的已完成匯入單：系統應收列清掉，只剩匯入時的歷史收款列（應收 0、實收已確認）。"""
        kwargs.setdefault("source_type", "store")
        kwargs.setdefault("source", self.staff)
        order = self.make_order(**kwargs)
        SalesOrder.all_objects.filter(pk=order.pk).update(status=status)
        if legacy:
            row = LegacyImportRow.objects.create(batch=self.batch, sheet_name="銷貨", source_row=order.pk,
                                                 fingerprint=f"t276-{order.pk}")
            LegacySalesSnapshot.objects.create(order=order, import_row=row)
        with payment_ledger_maintenance():
            PaymentRecord.objects.filter(order=order).delete()
            PaymentRecord.objects.create(order=order, item_name="歷史收款", system_key="legacy_cash",
                                         **(receipt or {"expected_amount": 0, "received_amount": 70000,
                                                        "confirmed": True}))
        if confirmed is not None:
            OrderOperationsProfile.objects.filter(order=order).update(payment_confirmed=confirmed)
        return SalesOrder.objects.get(pk=order.pk)

    def pair(self, **kwargs):
        return self.order(False, **kwargs), self.order(True, **kwargs)

    # ── 收款：payment_summary 底層 ──

    def test_completed_imported_order_is_settled_without_changing_amounts(self):
        system, imported = self.pair()
        self.assertFalse(payment_summary(system)["settled"])  # 系統單照訂單欄位推算應收，尾款未收清
        summary = payment_summary(imported)
        self.assertTrue(summary["settled"])
        # 金額照舊：匯入歷史單應收只看收款列（應收 0），所以舊規則是「沒有應收金額，不標已收清」。
        self.assertEqual([summary[k] for k in UNCHANGED_KEYS], [0, 0, 0, 0, 0, True, 0, 0])

    def test_imported_order_with_open_legacy_receivable_is_settled_but_keeps_due_flags(self):
        owing = {"expected_amount": 500, "received_amount": 100, "confirmed": True}
        system, imported = self.pair(receipt=owing)
        self.assertFalse(payment_summary(system)["settled"])
        summary = payment_summary(imported)
        self.assertTrue(summary["settled"])
        self.assertFalse(summary["legacy_settled"])  # 統計類（T-275 已另行排除）讀的欄位不變
        self.assertEqual(summary["customer_due"], Decimal("400"))

    def test_open_imported_order_still_follows_receipts(self):
        owing = {"expected_amount": 500, "received_amount": 100, "confirmed": True}
        for status in ("delivery_pending", "allocated"):
            system, imported = self.pair(status=status, receipt=owing)
            self.assertFalse(payment_summary(imported)["settled"], status)
            self.assertFalse(payment_summary(system)["settled"], status)

    def test_receipt_status_card_shows_settled_for_imported_order(self):
        # 訂單頁只有非本店單顯示收款狀態卡。
        system, imported = self.pair(source_type="dealer", source=self.dealer)
        self.assertFalse(receipt_status(system, payment_summary(system))["settled"])
        self.assertTrue(receipt_status(imported, payment_summary(imported))["settled"])
        self.client.force_login(self.admin)
        page = self.client.get(reverse("order_detail", args=[imported.pk]) + "?tab=finance").content.decode()
        self.assertIn("款項已全部收清", page)
        self.assertNotIn("這張單目前沒有應收金額", page)
        page = self.client.get(reverse("order_detail", args=[system.pk]) + "?tab=finance").content.decode()
        self.assertIn("款項還沒收清", page)

    def test_resave_keeps_imported_payment_confirmed_true(self):
        """正式站 1,502 張匯入單存的是已收款、舊算法卻是未收清：動到收款列重算時不能被改成待確認。"""
        system, imported = self.pair(confirmed=True)
        _profile, changes = payment_confirmation_changes(imported.pk)
        self.assertNotIn("payment_confirmed", changes)
        _profile, changes = payment_confirmation_changes(system.pk)
        self.assertEqual(changes["payment_confirmed"], (True, False))
        PaymentRecord.objects.filter(order=imported).first().save()
        self.assertTrue(self.profile(imported).payment_confirmed)

    def test_audit_no_longer_flags_imported_orders_saved_as_confirmed(self):
        self.pair(confirmed=True)
        codes = [sample["code"] for sample in audit_financial_consistency(sample_limit=100)["samples"]
                 if sample["code"] == "payment_confirmation_mismatch"]
        self.assertEqual(len(codes), 1)  # 只剩系統單

    # ── 收款：讀存檔旗標的篩選與報表 ──

    def test_pending_filter_skips_imported_orders(self):
        system, imported = self.pair(confirmed=False)
        rows = SalesOrder.objects.filter(pk__in=[system.pk, imported.pk])
        pending = set(filter_order_analysis(rows, {"payment_status": "pending"}).values_list("pk", flat=True))
        confirmed = set(filter_order_analysis(rows, {"payment_status": "confirmed"}).values_list("pk", flat=True))
        self.assertEqual((pending, confirmed), ({system.pk}, {imported.pk}))

    def test_open_imported_order_filter_uses_saved_flag(self):
        system, imported = self.pair(status="delivery_pending", confirmed=False)
        rows = SalesOrder.objects.filter(pk__in=[system.pk, imported.pk])
        pending = set(filter_order_analysis(rows, {"payment_status": "pending"}).values_list("pk", flat=True))
        self.assertEqual(pending, {system.pk, imported.pk})

    def test_report_record_column_and_sort(self):
        system, imported = self.pair(confirmed=False)
        cells = {order.pk: record_cells(order, ["payment_confirmed"])[0]["value"]
                 for order in record_queryset(self.report_config(), {})}
        self.assertEqual((cells[system.pk], cells[imported.pk]), ("未收款", "已收款"))
        ordered = [o.pk for o in record_queryset(self.report_config(), {"records_sort": "payment_confirmed"})]
        self.assertEqual(ordered, [system.pk, imported.pk])
        ordered = [o.pk for o in record_queryset(self.report_config(), {"records_sort": "-payment_confirmed"})]
        self.assertEqual(ordered, [imported.pk, system.pk])

    def report_config(self):
        return {"date_basis": "order_date", "cards": [], "include_records": True,
                "records_columns": ["payment_confirmed"]}

    # ── 補助 ──

    def subsidy_pair(self):
        return self.pair(is_trade_in_subsidy=True)  # 舊車牌、補助項目、舊車主都沒填

    def test_subsidy_step_and_action_skip_imported_orders(self):
        system, imported = self.subsidy_pair()
        self.assertTrue(system.missing_subsidy_requirements())
        self.assertEqual(imported.missing_subsidy_requirements(), system.missing_subsidy_requirements())
        self.assertEqual(_subsidy_step(system), ("todo", "補助資料待補"))
        self.assertEqual(_subsidy_step(imported), ("done", "匯入前已處理"))
        self.assertIn("subsidy", self.action_keys(system))
        self.assertNotIn("subsidy", self.action_keys(imported))

    def action_keys(self, order):
        actions = build_order_next_actions(order)
        return [action.key for action in ([actions.primary, *actions.secondary] if actions else [])]

    def test_imported_order_page_does_not_open_subsidy_tab(self):
        system, imported = self.subsidy_pair()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("order_detail", args=[system.pk]))
        self.assertEqual(response.context["open_step"], "subsidy")
        self.assertContains(response, "補助資料尚缺")
        response = self.client.get(reverse("order_detail", args=[imported.pk]))
        self.assertNotEqual(response.context["open_step"], "subsidy")
        self.assertEqual(response.context["subsidy_missing"], [])
        self.assertNotContains(response, "補助資料尚缺")
        self.assertContains(response, "Excel 匯入單不追蹤補助資料")

    def test_imported_order_subsidy_items_still_track_application(self):
        from sales.models import SubsidyItem
        _system, imported = self.subsidy_pair()
        SubsidyItem.objects.create(order=imported, category="other", item_name="汰舊換新")
        imported = SalesOrder.objects.get(pk=imported.pk)
        self.assertEqual(_subsidy_step(imported), ("todo", "0／1 項已申請"))
        self.assertEqual(build_order_next_actions(imported).primary.title, "送出補助申請")

    # ── 訂單匯出 ──

    def test_export_marks_imported_orders_confirmed(self):
        system, imported = self.pair(payment_type="installment", confirmed=False)
        for key in ("payment_confirmed", "installment_transfer_confirmed"):
            getter = COLUMN_BY_KEY[key].getter
            self.assertIs(getter(imported), True, key)
            self.assertIs(getter(system), False, key)

    # ── Excel 匯入已修改（使用者 2026-11-21 補充）──

    def edited(self, **kwargs):
        _system, imported = self.pair(**kwargs)
        OrderEvent.objects.create(order=imported, event_type="operations_updated", actor_name="Staffc",
                                  description="修改收支（2 個欄位）")
        imported = SalesOrder.objects.get(pk=imported.pk)
        self.assertEqual(current_order_origin(imported).key, IMPORTED_EDITED)
        return imported

    def test_edited_imported_order_is_settled_like_other_imports(self):
        order = self.edited(payment_type="installment", is_trade_in_subsidy=True, confirmed=False)
        self.assertTrue(payment_summary(order)["settled"])
        self.assertTrue(receipt_status(order, payment_summary(order))["settled"])
        rows = SalesOrder.objects.filter(pk=order.pk)
        self.assertFalse(filter_order_analysis(rows, {"payment_status": "pending"}).exists())
        self.assertEqual(record_cells(order, ["payment_confirmed"])[0]["value"], "已收款")
        for key in ("payment_confirmed", "installment_transfer_confirmed"):
            self.assertIs(COLUMN_BY_KEY[key].getter(order), True, key)
        self.assertEqual(_subsidy_step(order), ("done", "匯入前已處理"))
        self.assertNotIn("subsidy", self.action_keys(order))

    def test_edited_imported_order_keeps_staff_amounts(self):
        order = self.edited(confirmed=True)
        OrderOperationsProfile.objects.filter(order=order).update(
            vehicle_cost=Decimal("55555"), registration_tax_expense=Decimal("999"), agency_fee_income=Decimal("321"))
        # 人員補登一筆實收（已確認的收款不能直接改，要沖銷；補登是人員修改匯入單收款的路徑）。
        PaymentRecord.objects.create(order=order, item_name="補收", received_amount=Decimal("2000"),
                                     receipt_kind="customer", confirmed=True, payment_method="現金")
        order = SalesOrder.objects.get(pk=order.pk)
        order.owner_phone = "0922333444"
        order.save()
        sync_order_operations(order.pk, update_receivables=True)
        profile = self.profile(order)
        self.assertEqual((profile.vehicle_cost, profile.registration_tax_expense, profile.agency_fee_income),
                         (Decimal("55555"), Decimal("999"), Decimal("321")))
        receipt = PaymentRecord.objects.get(order=order, system_key="legacy_cash")
        self.assertEqual((receipt.expected_amount, receipt.received_amount), (Decimal("0"), Decimal("70000")))
        summary = payment_summary(SalesOrder.objects.get(pk=order.pk))
        self.assertEqual((summary["customer_expected"], summary["customer_received"], summary["customer_due"]),
                         (Decimal("0"), Decimal("72000"), Decimal("0")))
        self.assertTrue(summary["settled"])
        self.assertTrue(profile.payment_confirmed)
