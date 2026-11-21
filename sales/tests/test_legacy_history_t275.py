"""T-275 第 8 項（使用者 2026-11-21 選 A）：Excel 匯入單＝歷史資料，一律視為已收款、已對帳。

規則只放在統計與篩選層，不寫資料：
- 營運總表／首頁的款項數字、全部訂單的收款風險篩選、「款項未結清」紅標、車行到期提醒都不算匯入單。
- `payment_summary`（訂單頁收款摘要、交車頁應收）、統一撥款對帳、交車掛帳額度檢查、收款帳溢收不變。
"""
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone

from sales.models import LegacyImportBatch, LegacyImportRow, LegacySalesSnapshot, PaymentRecord, SalesOrder
from sales.services import operations_cockpit
from sales.services.business_days import build_dealer_reminders
from sales.services.dashboard_metrics import build_dashboard_metrics
from sales.services.order_list_unsettled import mark_unsettled
from sales.services.payment_summary import payment_summary
from sales.services.sales_metrics import filter_payment_risk
from sales.tests.test_finance_ledger import FinanceLedgerTestBase

MONEY_RISKS = ("outstanding", "unsettled_delivered", "unconfirmed", "refund", "overpaid", "before_delivery",
               "awaiting_payout")


class LegacyHistoryTests(FinanceLedgerTestBase):
    def setUp(self):
        cache.clear()
        self.today = timezone.localdate()
        self.batch = LegacyImportBatch.objects.create(import_type="operations", original_filename="synthetic.xlsx",
                                                      file_size=0)

    def order(self, status, legacy, **kwargs):
        kwargs.setdefault("source_type", "store")
        kwargs.setdefault("source", self.staff)
        order = self.make_order(**kwargs)
        SalesOrder.all_objects.filter(pk=order.pk).update(status=status)
        if legacy:
            row = LegacyImportRow.objects.create(batch=self.batch, sheet_name="銷貨", source_row=order.pk,
                                                 fingerprint=f"t275-history-{order.pk}")
            LegacySalesSnapshot.objects.create(order=order, import_row=row)
        return SalesOrder.objects.get(pk=order.pk)

    def pair(self, status, record=None, **kwargs):
        """同樣條件的系統單與匯入單各一張；回傳 (系統單, 匯入單)。"""
        orders = []
        for legacy in (False, True):
            order = self.order(status, legacy, **kwargs)
            if record:
                PaymentRecord.objects.create(order=order, **record)
            orders.append(SalesOrder.objects.get(pk=order.pk))
        return orders

    def ids(self, risk):
        return set(filter_payment_risk(SalesOrder.objects.all(), risk).values_list("pk", flat=True))

    # ── 全部訂單篩選、營運總表 ──

    def test_money_risks_skip_imported_orders(self):
        owing = {"expected_amount": 500, "received_amount": 100, "confirmed": True}
        delivered = self.pair("completed", owing)
        unconfirmed = self.pair("completed", {"expected_amount": 500, "received_amount": 500, "confirmed": False})
        before = self.pair("delivery_pending", owing)
        refund = self.pair("cancel_refund_pending")
        payout = self.pair("completed", {"receipt_kind": "lender", "expected_amount": 500, "received_amount": 0})
        overpaid = self.pair("delivery_pending", {"expected_amount": 0, "received_amount": 999999, "confirmed": True},
                             cash_receivable_v2=True)
        imported = {pair[1].pk for pair in (delivered, unconfirmed, before, refund, payout, overpaid)}
        for risk in MONEY_RISKS:
            self.assertFalse(self.ids(risk) & imported, risk)
        self.assertIn(delivered[0].pk, self.ids("unsettled_delivered"))
        self.assertIn(unconfirmed[0].pk, self.ids("unconfirmed"))
        self.assertIn(before[0].pk, self.ids("before_delivery"))
        self.assertIn(refund[0].pk, self.ids("refund"))
        self.assertIn(overpaid[0].pk, self.ids("overpaid"))
        # 非款項的篩選照舊含匯入單。
        self.assertIn(before[1].pk, set(SalesOrder.objects.filter(status="delivery_pending").values_list("pk", flat=True)))

    def test_cockpit_and_dashboard_numbers_skip_imported_orders(self):
        owing = {"expected_amount": 500, "received_amount": 100, "confirmed": True}
        self.pair("completed", owing)
        self.pair("delivery_pending", owing)
        self.pair("completed", {"expected_amount": 500, "received_amount": 500, "confirmed": False})
        self.pair("cancel_refund_pending")
        metrics = build_dashboard_metrics(self.today)
        self.assertEqual(metrics["risk"]["outstanding"], 3)
        self.assertEqual(metrics["risk"]["unconfirmed"], 1)
        self.assertEqual(metrics["risk"]["refund"], 1)
        for key, rows in metrics["risk_orders"].items():
            self.assertFalse(rows.filter(legacy_snapshot__isnull=False).exists(), key)
        money = operations_cockpit.build("month", self.today)["money"]
        self.assertEqual((money["unsettled_count"], money["before_delivery_count"]), (2, 1))
        self.assertEqual(money["outstanding_count"], 3)

    # ── 紅標、到期提醒 ──

    def test_unsettled_mark_skips_imported_orders(self):
        system, imported = self.pair("completed", {"expected_amount": 500, "received_amount": 100, "confirmed": True})
        orders = mark_unsettled(list(SalesOrder.objects.filter(pk__in=[system.pk, imported.pk]).order_by("pk")))
        marks = {order.pk: order.unsettled_due for order in orders}
        self.assertEqual(marks[system.pk], payment_summary(SalesOrder.objects.get(pk=system.pk))["customer_due"])
        self.assertGreater(marks[system.pk], 0)
        self.assertIsNone(marks[imported.pk])

    def test_dealer_reminders_skip_imported_orders_entirely(self):
        long_ago = timezone.now() - timedelta(days=40)
        system, imported = self.pair("delivered_docs_pending", source_type="dealer", source=self.dealer)
        SalesOrder.all_objects.filter(pk__in=[system.pk, imported.pk]).update(delivered_at=long_ago)
        reminders = build_dealer_reminders(self.today)
        kinds = {(item["order"].pk, item["kind"]) for item in reminders}
        self.assertIn((system.pk, "dealer_balance"), kinds)
        self.assertIn((system.pk, "registration_documents"), kinds)
        self.assertFalse({pk for pk, _kind in kinds} & {imported.pk})

    # ── Excel 匯入已修改（使用者 2026-11-21：匯入後有人改過也算已完成，處理同其他匯入單）──

    def test_edited_imported_orders_are_still_settled_history(self):
        from sales.models import OrderEvent
        from sales.services.order_origin import IMPORTED_EDITED, current_order_origin

        owing = {"expected_amount": 500, "received_amount": 100, "confirmed": True}
        system, edited = self.pair("completed", owing, source_type="dealer", source=self.dealer)
        OrderEvent.objects.create(order=edited, event_type="updated", actor_name="Staffc",
                                  description="修改訂單（2 個項目）")
        self.assertEqual(current_order_origin(SalesOrder.objects.get(pk=edited.pk)).key, IMPORTED_EDITED)
        SalesOrder.all_objects.filter(pk__in=[system.pk, edited.pk]).update(
            delivered_at=timezone.now() - timedelta(days=40))
        for risk in MONEY_RISKS:
            self.assertNotIn(edited.pk, self.ids(risk), risk)
        self.assertIn(system.pk, self.ids("unsettled_delivered"))
        marks = {o.pk: o.unsettled_due for o in mark_unsettled(list(SalesOrder.objects.filter(
            pk__in=[system.pk, edited.pk])))}
        self.assertIsNone(marks[edited.pk])
        self.assertNotIn(edited.pk, {item["order"].pk for item in build_dealer_reminders(self.today)})
        money = operations_cockpit.build("month", self.today)["money"]
        self.assertEqual(money["unsettled_count"], 1)

    # ── 不適用範圍：payment_summary 不變 ──

    def test_payment_summary_of_imported_order_is_unchanged(self):
        _system, imported = self.pair("completed", {"expected_amount": 500, "received_amount": 100, "confirmed": True})
        _s, unconfirmed = self.pair("completed", {"expected_amount": 500, "received_amount": 500, "confirmed": False})
        # 數字取自規則加上前（c5e34e8f）的 payment_summary：匯入單在訂單頁、交車頁看到的應收不變。
        keys = ("customer_due", "lender_due", "legacy_settled", "customer_overpaid")
        self.assertEqual([payment_summary(SalesOrder.objects.get(pk=imported.pk))[k] for k in keys],
                         [Decimal("82550"), Decimal("0"), False, Decimal("0")])
        self.assertEqual([payment_summary(SalesOrder.objects.get(pk=unconfirmed.pk))[k] for k in keys],
                         [Decimal("82650"), Decimal("0"), False, Decimal("0")])
