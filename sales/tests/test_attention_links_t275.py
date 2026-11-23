"""T-275：營運總表「需要處理」每一項點進去，只看到卡片算到的那一批（筆數相同、同一批 ID）。

正式站 v2.34.0 對不上的五項（庫齡、交車後未結清、缺貨、卡關、原廠獎勵）與沒有連結的「車行掛帳超過額度」
在這裡用合成資料重現；正式站目前是 0 的項目（取消待退款、溢收待退、傭金未給付、掛帳超額）也一併比對。
目的頁不帶新參數時，行為照舊（另有測試）。
"""
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from sales.models import IncentiveCampaign, PaymentRecord, SalesOrder, Store, VehicleColor, VehicleInventory, VehicleModel
from sales.services.dealer_commission import apply_order_dealer_commission
from sales.services.operations_sync import sync_order_operations
from sales.tests.test_finance_ledger import FinanceLedgerTestBase


def models_q_payout():
    from django.db.models import Q
    return Q(receipt_kind="lender") | Q(system_key__in=PaymentRecord.PAYOUT_KEYS)


class AttentionLinkTests(FinanceLedgerTestBase):
    def setUp(self):
        cache.clear()
        self.today = timezone.localdate()
        self.client.force_login(self.admin)

    # ── 共用 ──

    def attention(self):
        response = self.client.get(reverse("operations_report"))
        self.assertEqual(response.status_code, 200)
        return {item["key"]: item for item in response.context["cockpit"]["attention"]}

    def follow(self, item):
        self.assertTrue(item["url"], f"{item['label']} 沒有連結")
        response = self.client.get(item["url"])
        self.assertEqual(response.status_code, 200, item["url"])
        return response

    def order_ids(self, response):
        return {order.pk for order in response.context["page_obj"].paginator.object_list}

    def store_order(self, status="completed", **kwargs):
        order = self.make_order(source_type="store", source=self.staff, **kwargs)
        SalesOrder.all_objects.filter(pk=order.pk).update(status=status)
        return SalesOrder.objects.get(pk=order.pk)

    def owing(self, order, expected=500, received=100):
        PaymentRecord.objects.create(order=order, expected_amount=expected, received_amount=received, confirmed=True)
        return order

    def settle(self, order):
        """客人應付全部收清（已確認），分期／平台撥款不動。"""
        from sales.services.payment_summary import payment_summary
        due = payment_summary(SalesOrder.objects.get(pk=order.pk))["customer_due"]
        if due > 0:
            PaymentRecord.objects.create(order=order, expected_amount=0, received_amount=due, confirmed=True)
        self.assertEqual(payment_summary(SalesOrder.objects.get(pk=order.pk))["customer_due"], 0)
        return order

    def assert_same_batch(self, key, expected_ids, response_ids):
        item = self.attention()[key] if expected_ids else None
        if item is None:
            self.fail(f"{key} 應出現在需要處理")
        self.assertEqual(item["value"], len(expected_ids), key)
        self.assertEqual(response_ids(self.follow(item)), set(expected_ids), key)
        return item

    # ── 1. 交車後未結清 ──

    def test_unsettled_after_delivery_lists_only_delivered_orders_still_owing(self):
        completed = self.owing(self.store_order("completed"))
        docs = self.owing(self.store_order("delivered_docs_pending"))
        before = self.owing(self.store_order("delivery_pending"))           # 交車前：不算
        lender = self.store_order("completed")                              # 只剩分期撥款：不算
        PaymentRecord.objects.create(order=lender, receipt_kind="lender", expected_amount=500, received_amount=0)
        self.settle(lender)
        self.owing(self.store_order("cancelled"))                           # 取消：不算
        self.settle(self.store_order("completed"))                          # 已收清：不算
        item = self.assert_same_batch("unsettled_cash", {completed.pk, docs.pk}, self.order_ids)  # 第 9 項依付款方式拆列
        self.assertIn("risk=unsettled_delivered", item["url"])
        # 原本的「待收款」照舊（含交車前、撥款未到）。
        wide = self.order_ids(self.client.get(reverse("order_list"), {"risk": "outstanding"}))
        self.assertTrue({before.pk, lender.pk} <= wide)

    # ── 2. 流程卡關 ──

    def test_stuck_lists_every_stage_over_its_limit(self):
        now = timezone.now()
        stuck = []

        def make(status, **fields):
            order = self.store_order(status)
            SalesOrder.all_objects.filter(pk=order.pk).update(**fields)
            return order.pk

        stuck.append(make("allocation_pending", established_on=self.today - timedelta(days=4)))
        make("allocation_pending", established_on=self.today - timedelta(days=3))
        stuck.append(make("allocated", allocated_at=now - timedelta(days=31)))
        make("allocated", allocated_at=now - timedelta(days=29))
        stuck.append(make("delivery_pending", registration_completed_at=now - timedelta(days=8)))
        make("delivery_pending", registration_completed_at=now - timedelta(days=6))
        stuck.append(make("delivered_docs_pending", delivered_at=now - timedelta(days=15)))
        make("delivered_docs_pending", delivered_at=now - timedelta(days=13))
        item = self.assert_same_batch("stuck", set(stuck), self.order_ids)
        self.assertIn("attention=stuck", item["url"])
        response = self.follow(item)
        self.assertContains(response, "流程卡關")

    # ── 3. 庫齡 90 天以上 ──

    def vehicle(self, number, days, status="available"):
        store = Store.objects.get_or_create(code="T275", defaults={"name": "T-275 測試店"})[0]
        return VehicleInventory.objects.create(
            vehicle_model=self.model, color=self.color, engine_number=f"ENG-T275-{number:04d}", ownership_store=store,
            location_store=store, status=status, received_on=self.today - timedelta(days=days)).pk

    def vehicle_ids(self, response):
        return {vehicle.pk for vehicle in response.context["page_obj"].paginator.object_list}

    def test_aged_stock_lists_only_vehicles_at_least_90_days(self):
        old = {self.vehicle(1, 95), self.vehicle(2, 90, "reserved"), self.vehicle(3, 120, "condition_issue")}
        young = self.vehicle(4, 89)
        self.vehicle(5, 400, "sold")
        item = self.assert_same_batch("aged", old, self.vehicle_ids)
        self.assertIn("age_min=90", item["url"])
        # 不帶參數：全部在庫照舊。
        self.assertEqual(self.vehicle_ids(self.client.get(reverse("inventory_list"))), old | {young})

    # ── 4. 原廠獎勵 30 天內結束 ──

    def campaign(self, name, start=-5, end=10, active=True):
        return IncentiveCampaign.objects.create(
            name=name, active=active, effective_from=self.today + timedelta(days=start),
            effective_to=self.today + timedelta(days=end) if end is not None else None).pk

    def campaign_ids(self, response):
        return {campaign.pk for campaign in response.context["page_obj"].paginator.object_list}

    def test_campaigns_ending_lists_only_those_ending_within_30_days(self):
        ending = {self.campaign("十天後結束"), self.campaign("今天結束", end=0), self.campaign("三十天後結束", end=30)}
        others = {self.campaign("三十一天後", end=31), self.campaign("沒有結束日", end=None),
                  self.campaign("預定生效", start=3, end=10)}
        self.campaign("已停用", end=5, active=False)
        self.campaign("已失效", start=-30, end=-1)
        item = self.assert_same_batch("campaigns", ending, self.campaign_ids)
        self.assertIn("ending_within=30", item["url"])
        # 不帶參數：啟用中頁籤照舊（含已失效、預定生效）。
        everything = self.campaign_ids(self.client.get(reverse("incentive_rule_list")))
        self.assertTrue(ending | others <= everything)

    # ── 5. 缺貨風險車型（使用者選 A：列車型、在庫台數、近 90 天領牌台數、可銷天數）──

    def sold(self, model, count):
        color = VehicleColor.objects.get_or_create(vehicle_model=model, name="白")[0]
        for offset in range(count):
            order = self.store_order("completed", vehicle_model=model, color=color)
            SalesOrder.all_objects.filter(pk=order.pk).update(
                registration_date=self.today - timedelta(days=offset + 1), registration_completed_at=timezone.now())

    def test_shortage_lists_models_with_stock_counts_and_cover_days(self):
        empty = VehicleModel.objects.create(brand="SUZUKI", name="缺貨零庫存", energy_type="gas")
        thin = VehicleModel.objects.create(brand="SUZUKI", name="缺貨一台", energy_type="gas")
        fine = VehicleModel.objects.create(brand="SUZUKI", name="庫存足夠", energy_type="gas")
        few = VehicleModel.objects.create(brand="SUZUKI", name="賣不到三台", energy_type="gas")
        self.sold(empty, 3)
        self.sold(thin, 10)
        self.sold(fine, 3)
        self.sold(few, 2)
        store = Store.objects.get_or_create(code="T275", defaults={"name": "T-275 測試店"})[0]
        for number, model in enumerate((thin, fine), start=1):
            color = VehicleColor.objects.get_or_create(vehicle_model=model, name="白")[0]
            VehicleInventory.objects.create(vehicle_model=model, color=color, engine_number=f"ENG-T275-S{number}",
                                            ownership_store=store, location_store=store, status="available",
                                            received_on=self.today)
        item = self.assert_same_batch("shortage", {empty.pk, thin.pk},
                                      lambda response: {row["model_id"] for row in response.context["rows"]})
        rows = {row["model_id"]: row for row in self.follow(item).context["rows"]}
        self.assertEqual((rows[empty.pk]["on_hand"], rows[empty.pk]["sold"], rows[empty.pk]["cover"]), (0, 3, 0))
        self.assertEqual((rows[thin.pk]["on_hand"], rows[thin.pk]["sold"], rows[thin.pk]["cover"]), (1, 10, 9))
        response = self.follow(item)
        for text in ("缺貨零庫存", "在庫台數", "近 90 天領牌", "可銷天數"):
            self.assertContains(response, text)
        self.assertNotContains(response, "庫存足夠")

    # ── 6. 車行未付（T-288 起沒有額度，「需要處理」不列；清單頁列全部）──

    def on_account(self, dealer):
        order = self.make_order(source=dealer, cash_receivable_v2=True)
        apply_order_dealer_commission(order)
        sync_order_operations(order.pk)
        SalesOrder.all_objects.filter(pk=order.pk).update(status="completed")
        return order.pk

    def test_dealer_credit_has_no_attention_item_and_list_shows_all_dealers(self):
        """T-288：車行額度移除，「需要處理」不再有車行未付超額度；清單頁不帶參數就列全部有未付的車行與訂單。"""
        dealer_orders = {self.on_account(self.dealer), self.on_account(self.dealer)}
        other_order = self.on_account(self.other_dealer)
        self.assertNotIn("dealer_credit", self.attention())
        response = self.client.get(reverse("operations_dealer_credit"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual({row["dealer"].pk for row in response.context["dealers"]},
                         {self.dealer.pk, self.other_dealer.pk})
        listed = {order.pk for row in response.context["dealers"] for order, _due in row["orders"]}
        self.assertEqual(listed, dealer_orders | {other_order})
        self.assertContains(response, "結算車行")
        self.assertContains(response, "歸屬車行")                 # 原本未超額的車行現在也列
        self.assertNotContains(response, "額度")

    # ── 已對得上的項目：正式站多為 0，用合成資料補比對 ──

    def test_refund_overpaid_and_unconfirmed_match_their_pages(self):
        refund = self.store_order("cancel_refund_pending").pk
        self.assert_same_batch("refund", {refund}, self.order_ids)
        overpaid = self.make_order(source_type="store", source=self.staff, cash_receivable_v2=True)
        PaymentRecord.objects.create(order=overpaid, expected_amount=0, received_amount=999999, confirmed=True)
        self.assert_same_batch("overpaid", {overpaid.pk}, self.order_ids)
        unconfirmed = self.store_order("allocation_pending")
        PaymentRecord.objects.create(order=unconfirmed, expected_amount=500, received_amount=100, confirmed=False)
        self.assert_same_batch("unconfirmed", {unconfirmed.pk}, self.order_ids)

    def test_reconciliation_pending_counts_orders_and_page_groups_by_order(self):
        # 使用者 2026-11-21：撥款待入帳改算「張」，和「已交車待撥款」同單位；一張單有兩筆撥款也只算一張。
        orders = []
        for _ in range(2):
            orders.append(self.make_order(source_type="platform", source=self.platform, vehicle_price=Decimal("0"),
                                          plate_insurance_fee=Decimal("2100")))
        PaymentRecord.objects.create(order=orders[0], receipt_kind="lender", expected_amount=500, received_amount=0)
        records = PaymentRecord.objects.filter(order__in=orders).filter(
            models_q_payout()).values_list("pk", flat=True)
        self.assertEqual(len(records), 3)
        item = self.assert_same_batch(
            "reconciliation_platform", {order.pk for order in orders},  # 第 9 項依撥款來源拆列
            lambda response: {row.order_id for row in response.context["page_obj"].paginator.object_list})
        self.assertEqual(item["unit"], "張")
        response = self.follow(item)
        self.assertEqual(response.context["order_count"], 2)
        self.assertContains(response, "2 張")
        self.assertContains(response, "3 筆撥款")
        # 「錢」卡片同一個數字、同一個單位。
        report = self.client.get(reverse("operations_report"))
        self.assertContains(report, "?status=pending&amp;by_order=1&amp;channel=platform\">2 張</a>")
        # 不帶 by_order：撥款對帳照舊列紀錄筆數。
        plain = self.client.get(reverse("reconciliation_list"), {"status": "pending"})
        self.assertEqual(plain.context["page_obj"].paginator.count, 3)
        self.assertNotIn("order_count", plain.context)

    def test_unpaid_payouts_match_their_page(self):
        orders = []
        for _ in range(2):
            order = self.make_order()
            SalesOrder.all_objects.filter(pk=order.pk).update(
                registration_date=self.today - timedelta(days=1), registration_completed_at=timezone.now(),
                status="completed")
            orders.append(order.pk)

        def keys(response):
            return {item.source_key for group in response.context["groups"] for row in group["orders"]
                    for item in row["items"]} | {item.source_key for group in response.context["groups"]
                                                 for item in group["bonuses"]}

        item = self.attention()["payouts"]
        listed = keys(self.follow(item))
        self.assertEqual(item["value"], len(listed))
        self.assertEqual({f"commission:order:{pk}" for pk in orders}, listed)

    # ── 車行到期提醒（QA 補測）──

    def test_dealer_due_matches_order_list_attention_dealer(self):
        from sales.models import LegacyImportBatch, LegacyImportRow, LegacySalesSnapshot
        long_ago = timezone.now() - timedelta(days=20)

        def dealer_order(status="completed", delivered_at=long_ago, source_type="dealer", legacy=False):
            source = self.dealer if source_type == "dealer" else self.staff
            order = self.make_order(source_type=source_type, source=source)
            sync_order_operations(order.pk)
            SalesOrder.all_objects.filter(pk=order.pk).update(status=status, delivered_at=delivered_at)
            if legacy:
                batch = LegacyImportBatch.objects.create(import_type="operations", original_filename="t275.xlsx",
                                                         file_size=0)
                row = LegacyImportRow.objects.create(batch=batch, sheet_name="銷貨", source_row=order.pk,
                                                     fingerprint=f"t275-dealer-due-{order.pk}")
                LegacySalesSnapshot.objects.create(order=order, import_row=row)
            return order.pk

        # 尾款未確認且領牌文件未完成：同一張單兩則提醒，卡片與清單都只算一張。
        due = {dealer_order("completed"), dealer_order("delivered_docs_pending"),
               dealer_order("cancel_refund_pending")}
        dealer_order("completed", delivered_at=timezone.now())     # 剛交車，還沒到期
        dealer_order("completed", legacy=True)                      # Excel 匯入單：不提醒
        dealer_order("completed", source_type="store")              # 本店單：不提醒
        dealer_order("cancelled")                                   # 已取消：不提醒
        dealer_order("completed", delivered_at=None)                # 尚未交車：不提醒
        item = self.assert_same_batch("dealer_due", due, self.order_ids)
        self.assertIn("attention=dealer", item["url"])
