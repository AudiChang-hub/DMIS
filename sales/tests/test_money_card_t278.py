"""T-278／T-279／T-280（使用者 2026-11-21）：營運總表「錢」卡片與車行到期提醒。

- T-280：車行到期提醒的「尾款」只看車行要付的部分（客人應付），分期／平台撥款是事後對帳，跟車行無關。
- T-278 B1-A：非匯入、未取消、有未入帳「平台撥款」列的平台單算待收，金額用收支的預估車價收入。
- T-278 D1～D3、T-279：三格都有金額、分期撥款待入帳拆已交車／交車前、平台撥款顯示預估、車行掛帳可點進清單。
卡片數字和點進去的清單，張數與 ID 都要一致。
"""
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from sales.models import OrderOperationsProfile, PaymentRecord, SalesOrder
from sales.services.business_days import build_dealer_reminders
from sales.services.dealer_commission import apply_order_dealer_commission
from sales.services.operations_sync import refresh_payment_confirmation, sync_order_operations
from sales.services.payment_summary import payment_summary
from sales.tests.test_finance_ledger import FinanceLedgerTestBase

ZERO = Decimal("0")


class MoneyCardTestBase(FinanceLedgerTestBase):
    def setUp(self):
        cache.clear()
        self.today = timezone.localdate()
        self.client.force_login(self.admin)

    def cockpit(self):
        response = self.client.get(reverse("operations_report"))
        self.assertEqual(response.status_code, 200)
        return response, response.context["cockpit"]

    def attention(self):
        return {item["key"]: item for item in self.cockpit()[1]["attention"]}

    def order_ids(self, response):
        return {order.pk for order in response.context["page_obj"].paginator.object_list}

    def listed(self, params):
        response = self.client.get(reverse("order_list"), params)
        self.assertEqual(response.status_code, 200)
        return self.order_ids(response)

    def order(self, status="completed", delivered_at=None, **kwargs):
        order = self.make_order(**kwargs)
        sync_order_operations(order.pk)
        SalesOrder.all_objects.filter(pk=order.pk).update(status=status, delivered_at=delivered_at)
        return SalesOrder.objects.get(pk=order.pk)

    def settle(self, order):
        """客人應付全部收清（已確認），分期／平台撥款不動。"""
        due = payment_summary(SalesOrder.objects.get(pk=order.pk))["customer_due"]
        if due > 0:
            PaymentRecord.objects.create(order=order, expected_amount=0, received_amount=due, confirmed=True)
        refresh_payment_confirmation(order.pk)
        self.assertEqual(payment_summary(SalesOrder.objects.get(pk=order.pk))["customer_due"], 0)
        return order

    def lender_pending(self, order, amount=500):
        PaymentRecord.objects.create(order=order, receipt_kind="lender", expected_amount=amount, received_amount=0)
        refresh_payment_confirmation(order.pk)
        return order


class DealerDueReminderTests(MoneyCardTestBase):
    """T-280：正式站「車行到期」2 張都是車行分期單，客人已收清，只差分期公司撥款。"""

    def setUp(self):
        super().setUp()
        self.long_ago = timezone.now() - timedelta(days=30)

    def dealer_order(self, **kwargs):
        return self.order("completed", self.long_ago, source_type="dealer", source=self.dealer, **kwargs)

    def test_installment_waiting_only_for_lender_payout_is_not_dealer_balance_due(self):
        order = self.settle(self.lender_pending(self.dealer_order(payment_type="installment")))
        order.registration_completed_at = self.long_ago
        order.save(update_fields=["registration_completed_at", "updated_at"])
        self.assertFalse(OrderOperationsProfile.objects.get(order=order).payment_confirmed)   # 撥款未到＝未收清
        summary = payment_summary(SalesOrder.objects.get(pk=order.pk))
        self.assertEqual((summary["customer_due"] > 0, summary["lender_due"] > 0), (False, True))
        kinds = {(item["order"].pk, item["kind"]) for item in build_dealer_reminders(self.today)}
        self.assertNotIn((order.pk, "dealer_balance"), kinds)
        self.assertNotIn("dealer_due", self.attention())
        self.assertNotIn(order.pk, self.listed({"attention": "dealer"}))

    def test_dealer_still_owing_is_due_and_card_matches_list(self):
        cash = self.dealer_order()                                                     # 車行現金單沒收清
        installment_fee = self.lender_pending(self.dealer_order(payment_type="installment"))  # 分期單自付部分沒收清
        lender_only = self.settle(self.lender_pending(self.dealer_order(payment_type="installment")))
        for order in (cash, installment_fee, lender_only):
            SalesOrder.all_objects.filter(pk=order.pk).update(registration_completed_at=self.long_ago)
        due = {item["order"].pk for item in build_dealer_reminders(self.today)
               if item["is_due"] and item["kind"] == "dealer_balance"}
        self.assertEqual(due, {cash.pk, installment_fee.pk})
        item = self.attention()["dealer_due"]
        self.assertEqual(item["value"], 2)
        self.assertEqual(self.order_ids(self.client.get(item["url"])), {cash.pk, installment_fee.pk})
        _response, cockpit = self.cockpit()
        self.assertEqual(cockpit["flow"]["dealer_due"], 2)

    def test_query_count_does_not_grow_with_orders(self):
        # QA 疑慮 d：逐張算 payment_summary 不能每張多查資料庫（原本每張多查一次 legacy_snapshot）。
        def queries():
            with CaptureQueriesContext(connection) as captured:
                build_dealer_reminders(self.today)
            return len(captured.captured_queries)

        self.dealer_order()
        self.lender_pending(self.dealer_order(payment_type="installment"))
        few = queries()
        for _ in range(3):
            self.dealer_order()
            self.lender_pending(self.dealer_order(payment_type="installment"))
        self.assertEqual(len({item["order"].pk for item in build_dealer_reminders(self.today)}), 8)
        self.assertEqual(queries(), few)

    def test_label_states_due_rule(self):
        self.dealer_order()
        response, cockpit = self.cockpit()
        item = {row["key"]: row for row in cockpit["attention"]}["dealer_due"]
        self.assertEqual(item["label"], "車行尾款／領牌到期")
        self.assertIn("交車後第 7 個工作天起尾款未收清", item["detail"])
        self.assertContains(response, "交車後第 7 個工作天起尾款未收清、第 3 個工作天起領牌未完成")


class PlatformOutstandingTests(MoneyCardTestBase):
    """T-278 B1-A：平台撥款未入帳的平台單算待收，金額用收支的預估車價收入（畫面標預估）。"""

    def platform_order(self, status="completed", estimate=Decimal("61277"), **kwargs):
        order = self.order(status, timezone.now() if status == "completed" else None, source_type="platform",
                           source=self.platform, vehicle_price=Decimal("0"), **kwargs)
        self.assertTrue(order.payment_records.filter(system_key="platform_disbursement", confirmed=False).exists())
        self.settle(order)
        OrderOperationsProfile.objects.filter(order=order).update(actual_disbursement=estimate)
        return order

    def test_platform_awaiting_payout_counts_as_outstanding_and_lists_match(self):
        delivered = self.platform_order("completed", Decimal("61277"))
        before = self.platform_order("delivery_pending", Decimal("70000"))
        confirmed = self.platform_order("completed", Decimal("50000"))
        confirmed.payment_records.filter(system_key="platform_disbursement").update(
            received_amount=50000, confirmed=True, received_on=self.today)
        self.platform_order("cancelled", Decimal("40000"))                                    # 取消：不算
        response, cockpit = self.cockpit()
        money = cockpit["money"]
        self.assertEqual(money["outstanding_count"], 2)
        self.assertEqual(money["outstanding_amount"], Decimal("131277"))
        self.assertEqual((money["awaiting_payout_count"], money["awaiting_payout_amount"]), (1, Decimal("61277")))
        self.assertEqual((money["before_delivery_count"], money["before_delivery_amount"]), (1, Decimal("70000")))
        platform_row = {row["key"]: row for row in money["split"]["awaiting_payout"]}["platform"]
        self.assertEqual((platform_row["count"], platform_row["amount"], platform_row["estimated"]),
                         (1, Decimal("61277"), True))
        self.assertEqual(self.listed({"risk": "outstanding"}), {delivered.pk, before.pk})
        self.assertEqual(self.listed({"risk": "awaiting_payout"}), {delivered.pk})
        self.assertEqual(self.listed({"risk": "awaiting_payout", "pay": "platform"}), {delivered.pk})
        self.assertEqual(self.listed({"risk": "before_delivery"}), {before.pk})
        self.assertContains(response, "預估 $61,277")

    def test_estimate_marked_when_platform_is_before_delivery(self):
        # QA 疑慮 a：平台預估只落在交車前，待收合計和「交車前應收」的金額也要標預估。
        before = self.platform_order("delivery_pending", Decimal("70000"))
        response, cockpit = self.cockpit()
        money = cockpit["money"]
        self.assertEqual((money["before_delivery_count"], money["before_delivery_amount"]), (1, Decimal("70000")))
        self.assertEqual((money["awaiting_payout_count"], money["unsettled_count"]), (0, 0))
        self.assertEqual((money["before_delivery_estimated"], money["outstanding_estimated"]), (True, True))
        self.assertContains(response, "未交車・尾款待收 · 預估 $70,000")
        self.assertContains(response, '$70,000<small class="ops-facts__note">含平台撥款預估</small>')
        self.assertEqual(self.listed({"risk": "before_delivery"}), {before.pk})
        self.assertEqual(self.listed({"risk": "outstanding"}), {before.pk})

    def test_estimate_marked_when_platform_is_unsettled_payout(self):
        # QA 疑慮 a：平台預估落在交車後未結清那幾張的撥款，待收合計與那行撥款都標預估；交車後未結清本身只算客人應收。
        order = self.order("completed", timezone.now(), source_type="platform", source=self.platform,
                           vehicle_price=Decimal("0"))
        OrderOperationsProfile.objects.filter(order=order).update(actual_disbursement=Decimal("61277"))
        customer = payment_summary(SalesOrder.objects.get(pk=order.pk))["customer_due"]
        self.assertGreater(customer, 0)
        response, cockpit = self.cockpit()
        money = cockpit["money"]
        self.assertEqual((money["unsettled_count"], money["unsettled_amount"]), (1, customer))
        self.assertEqual(money["unsettled_payout_amount"], Decimal("61277"))
        self.assertEqual(money["outstanding_amount"], customer + Decimal("61277"))
        self.assertEqual((money["unsettled_payout_estimated"], money["outstanding_estimated"]), (True, True))
        self.assertEqual((money["before_delivery_estimated"], money["awaiting_payout_estimated"]), (False, False))
        self.assertContains(response, "含平台撥款預估")
        self.assertContains(response, "含交車後未結清那幾張的撥款 預估 $61,277")
        self.assertContains(response, f"交車後未結清 · ${customer:,.0f}<")
        self.assertEqual(self.listed({"risk": "unsettled_delivered"}), {order.pk})
        self.assertEqual(self.listed({"risk": "outstanding"}), {order.pk})

    def test_no_estimate_label_without_platform(self):
        before = self.order("delivery_pending", source_type="store", source=self.staff)
        awaiting = self.settle(self.lender_pending(
            self.order("completed", timezone.now(), source_type="store", source=self.staff, payment_type="installment"),
            amount=72300))
        response, cockpit = self.cockpit()
        money = cockpit["money"]
        self.assertFalse(any(money[key] for key in ("outstanding_estimated", "before_delivery_estimated",
                                                     "awaiting_payout_estimated", "unsettled_payout_estimated")))
        self.assertNotContains(response, "含平台撥款預估")
        self.assertNotContains(response, "未交車・尾款待收 · 預估")
        self.assertEqual(self.listed({"risk": "outstanding"}), {before.pk, awaiting.pk})

    def test_payment_summary_and_unsettled_mark_unchanged(self):
        order = self.platform_order("completed")
        summary = payment_summary(SalesOrder.objects.get(pk=order.pk))
        self.assertEqual((summary["customer_due"], summary["lender_due"]), (ZERO, ZERO))
        self.assertEqual(self.listed({"risk": "unsettled_delivered"}), set())

    def test_imported_platform_order_is_not_outstanding(self):
        from sales.models import LegacyImportBatch, LegacyImportRow, LegacySalesSnapshot
        order = self.platform_order("completed")
        batch = LegacyImportBatch.objects.create(import_type="operations", original_filename="t278.xlsx", file_size=0)
        row = LegacyImportRow.objects.create(batch=batch, sheet_name="銷貨", source_row=order.pk,
                                             fingerprint=f"t278-{order.pk}")
        LegacySalesSnapshot.objects.create(order=order, import_row=row)
        _response, cockpit = self.cockpit()
        self.assertEqual(cockpit["money"]["outstanding_count"], 0)
        self.assertEqual(self.listed({"risk": "outstanding"}), set())


class MoneyCardFiguresTests(MoneyCardTestBase):
    """T-278 D1～D3：三格都有金額、三格加起來等於待收合計；撥款待入帳拆列與預估。"""

    def test_three_cells_have_amounts_that_add_up_to_total(self):
        unsettled = self.order("completed", timezone.now(), source_type="store", source=self.staff)
        PaymentRecord.objects.create(order=unsettled, expected_amount=500, received_amount=100, confirmed=True)
        before = self.order("delivery_pending", source_type="store", source=self.staff)
        awaiting = self.settle(self.lender_pending(
            self.order("completed", timezone.now(), source_type="store", source=self.staff, payment_type="installment"),
            amount=72300))
        response, cockpit = self.cockpit()
        money = cockpit["money"]
        self.assertEqual(money["awaiting_payout_amount"], Decimal("72300"))
        self.assertEqual(money["before_delivery_amount"], payment_summary(before)["customer_due"])
        self.assertEqual(money["unsettled_amount"] + money["unsettled_payout_amount"] + money["before_delivery_amount"]
                         + money["awaiting_payout_amount"], money["outstanding_amount"])
        for bucket in ("unsettled", "before_delivery", "awaiting_payout"):
            self.assertEqual(sum((row["amount"] or ZERO for row in money["split"][bucket]), ZERO),
                             money[f"{bucket}_amount"], bucket)
        self.assertContains(response, f"已交車待撥款 · ${money['awaiting_payout_amount']:,.0f}")
        self.assertEqual(self.listed({"risk": "awaiting_payout"}), {awaiting.pk})

    def test_installment_reconciliation_split_delivered_and_before(self):
        delivered = self.lender_pending(self.order("completed", timezone.now(), payment_type="installment"), 72300)
        before = self.lender_pending(self.order("allocated", payment_type="installment"), 188160)
        response, cockpit = self.cockpit()
        row = {row["key"]: row for row in cockpit["reconciliation"]["channels"]}["installment"]
        self.assertEqual((row["delivered"]["count"], row["delivered"]["expected"]), (1, Decimal("72300")))
        self.assertEqual((row["before"]["count"], row["before"]["expected"]), (1, Decimal("188160")))
        self.assertEqual(row["pending"], 2)
        self.assertContains(response, '<small class="ops-facts__note">已交車 1・$72,300／交車前 1・$188,160</small>')
        # 點進去的撥款對帳（依訂單）＝同一批兩張（QA 疑慮 c）。
        self.assertEqual(self.reconciliation_ids("installment", response), {delivered.pk, before.pk})

    def reconciliation_ids(self, channel, report):
        url = f"{reverse('reconciliation_list')}?status=pending&amp;by_order=1&amp;channel={channel}"
        self.assertContains(report, f'href="{url}"')
        page = self.client.get(reverse("reconciliation_list"), {"status": "pending", "by_order": "1", "channel": channel})
        self.assertEqual(page.status_code, 200)
        ids = {row.order_id for row in page.context["page_obj"].paginator.object_list}
        self.assertEqual(page.context["order_count"], len(ids))
        return ids

    def test_installment_reconciliation_only_delivered_states_side(self):
        # QA 疑慮 b：只有一邊有單也要寫明是已交車還是交車前。
        first = self.lender_pending(self.order("completed", timezone.now(), payment_type="installment"), 72300)
        second = self.lender_pending(self.order("completed", timezone.now(), payment_type="installment"), 50000)
        response, cockpit = self.cockpit()
        row = {row["key"]: row for row in cockpit["reconciliation"]["channels"]}["installment"]
        self.assertEqual((row["pending"], row["delivered"]["count"], row["before"]["count"]), (2, 2, 0))
        self.assertContains(response, '<small class="ops-facts__note">已交車 2・$122,300</small>')
        self.assertNotContains(response, "交車前 0")
        self.assertEqual(self.reconciliation_ids("installment", response), {first.pk, second.pk})

    def test_installment_reconciliation_only_before_states_side(self):
        before = self.lender_pending(self.order("allocated", payment_type="installment"), 188160)
        response, cockpit = self.cockpit()
        row = {row["key"]: row for row in cockpit["reconciliation"]["channels"]}["installment"]
        self.assertEqual((row["pending"], row["delivered"]["count"], row["before"]["count"]), (1, 0, 1))
        self.assertContains(response, '<small class="ops-facts__note">交車前 1・$188,160</small>')
        self.assertNotContains(response, "已交車 0")
        self.assertEqual(self.reconciliation_ids("installment", response), {before.pk})

    def test_platform_reconciliation_shows_estimate(self):
        order = self.order("completed", timezone.now(), source_type="platform", source=self.platform,
                           vehicle_price=Decimal("0"))
        OrderOperationsProfile.objects.filter(order=order).update(actual_disbursement=Decimal("75810"))
        response, cockpit = self.cockpit()
        row = {row["key"]: row for row in cockpit["reconciliation"]["channels"]}["platform"]
        self.assertEqual((row["pending"], row["expected"], row["estimated"]), (1, Decimal("75810"), True))
        item = {item["key"]: item for item in cockpit["attention"]}["reconciliation_platform"]
        self.assertEqual((item["amount"], item["detail"]), (Decimal("75810"), "預估金額"))
        self.assertContains(response, "預估 $75,810")


class DealerCreditLinkTests(MoneyCardTestBase):
    """T-279：車行掛帳改連結、移除逐家列；D4-A 標明已含在交車後未結清、未設額度。"""

    def on_account(self, dealer):
        order = self.make_order(source=dealer, cash_receivable_v2=True)
        apply_order_dealer_commission(order)
        sync_order_operations(order.pk)
        SalesOrder.all_objects.filter(pk=order.pk).update(status="completed", delivered_at=timezone.now())
        return order.pk

    def test_card_links_to_dealer_orders_with_matching_counts(self):
        self.other_dealer.credit_limit = Decimal("10000000")
        self.other_dealer.save(update_fields=["credit_limit"])
        orders = {self.on_account(self.dealer), self.on_account(self.dealer), self.on_account(self.other_dealer)}
        response, cockpit = self.cockpit()
        money = cockpit["money"]
        self.assertEqual((len(money["dealer_credit"]), money["dealer_credit_orders"], money["dealer_credit_unlimited"]),
                         (2, 3, 1))
        url = reverse("operations_dealer_credit") + "?scope=all"
        self.assertContains(response, f'href="{url}"')
        self.assertContains(response, '車行掛帳<small class="ops-facts__note">已含在交車後未結清</small>')
        self.assertContains(response, "2 家・3 張，1 家未設額度")
        self.assertNotContains(response, f"<li><span>{self.dealer.name}</span>")       # 逐家列已移除
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertEqual({row["dealer"].pk for row in page.context["dealers"]}, {self.dealer.pk, self.other_dealer.pk})
        self.assertEqual({order.pk for row in page.context["dealers"] for order, _due in row["orders"]}, orders)
        self.assertContains(page, "未設額度")

    def test_default_page_still_lists_only_over_limit(self):
        self.on_account(self.dealer)                                           # 未設額度：預設頁不列
        page = self.client.get(reverse("operations_dealer_credit"))
        self.assertEqual(page.context["dealers"], [])
        self.assertContains(page, "車行掛帳超過額度")
