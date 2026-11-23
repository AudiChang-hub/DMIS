"""T-275 第 9 項（使用者 2026-11-21）：營運總表款項依付款方式拆成現金、刷卡、分期、平台四類。

- 判斷沿用既有欄位：平台單（source_type=platform）一律算平台，跟統一撥款對帳 channel 同一判斷；
  其餘依 payment_type（installment／card），其他算現金。
- 交車後未結清、交車前應收、已交車待撥款、撥款待入帳依四類拆列；每一列點進去是同一批訂單。
- 四類加起來等於原本的合計；待收合計、帳齡、已收款待確認、溢收、取消待退款不拆。
"""
from decimal import Decimal

from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from sales.models import PaymentRecord, SalesOrder
from sales.services import operations_cockpit
from sales.services.sales_metrics import PAYMENT_CATEGORIES, payment_category, payment_category_q
from sales.tests.test_finance_ledger import FinanceLedgerTestBase

KEYS = [key for key, _label in PAYMENT_CATEGORIES]


class PaymentSplitTests(FinanceLedgerTestBase):
    # ── 共用（同 test_attention_links_t275）──

    def setUp(self):
        cache.clear()
        self.today = timezone.localdate()
        self.client.force_login(self.admin)

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
        from sales.services.payment_summary import payment_summary
        due = payment_summary(SalesOrder.objects.get(pk=order.pk))["customer_due"]
        if due > 0:
            PaymentRecord.objects.create(order=order, expected_amount=0, received_amount=due, confirmed=True)
        self.assertEqual(payment_summary(SalesOrder.objects.get(pk=order.pk))["customer_due"], 0)
        return order

    def money(self):
        response = self.client.get(reverse("operations_report"))
        return response, response.context["cockpit"]["money"]

    def split(self, money, bucket):
        return {row["key"]: row for row in money["split"][bucket]}

    def categorized(self, status="completed"):
        """四類各一張：現金本店單、刷卡本店單、分期本店單、平台單（平台單填分期也算平台）。"""
        return {
            "cash": self.store_order(status),
            "card": self.store_order(status, payment_type="card"),
            "installment": self.store_order(status, payment_type="installment"),
            "platform": self.make_platform(status, payment_type="installment"),
        }

    def make_platform(self, status, **kwargs):
        order = self.make_order(source_type="platform", source=self.platform, **kwargs)
        SalesOrder.all_objects.filter(pk=order.pk).update(status=status)
        return SalesOrder.objects.get(pk=order.pk)

    # ── 判斷 ──

    def test_category_follows_existing_fields(self):
        orders = self.categorized()
        for key, order in orders.items():
            self.assertEqual(payment_category(order), key)
            self.assertEqual(set(SalesOrder.objects.filter(payment_category_q(key)).values_list("pk", flat=True)),
                             {order.pk}, key)
        self.assertEqual(KEYS, ["cash", "card", "installment", "platform"])

    # ── 交車後未結清 ──

    def test_unsettled_split_into_four_and_each_link_lists_same_batch(self):
        orders = self.categorized()
        for order in orders.values():
            self.owing(order)
        self.settle(self.store_order("completed", payment_type="card"))      # 已收清：不算
        attention = self.attention()
        for key, order in orders.items():
            item = attention[f"unsettled_{key}"]
            self.assertEqual(item["value"], 1, key)
            self.assertIn("risk=unsettled_delivered", item["url"])
            self.assertIn(f"pay={key}", item["url"])
            self.assertEqual(self.order_ids(self.follow(item)), {order.pk}, key)
        self.assertEqual(attention["unsettled_cash"]["label"], "交車後未結清（現金）")
        self.assertEqual(attention["unsettled_card"]["label"], "交車後未結清（刷卡）")
        self.assertEqual(attention["unsettled_installment"]["label"], "交車後未結清（分期，客人自付部分）")
        self.assertEqual(attention["unsettled_platform"]["label"], "交車後未結清（平台，客人自付部分）")
        _response, money = self.money()
        self.assertEqual(sum(row["count"] for row in money["split"]["unsettled"]), money["unsettled_count"])
        self.assertEqual(sum((row["amount"] for row in money["split"]["unsettled"]), Decimal("0")),
                         money["unsettled_amount"])

    def test_zero_categories_go_to_clear_list(self):
        self.owing(self.store_order("completed"))
        response = self.client.get(reverse("operations_report"))
        keys = [item["key"] for item in response.context["cockpit"]["attention"]]
        self.assertIn("unsettled_cash", keys)
        self.assertNotIn("unsettled_card", keys)
        self.assertIn("交車後未結清（刷卡）", response.context["cockpit"]["attention_clear"])

    # ── 交車前應收、已交車待撥款 ──

    def test_before_delivery_split_links_list_same_batch(self):
        orders = self.categorized("delivery_pending")
        for order in orders.values():
            self.owing(order)
        response, money = self.money()
        rows = self.split(money, "before_delivery")
        self.assertEqual(list(rows), KEYS)
        for key, order in orders.items():
            self.assertEqual(rows[key]["count"], 1, key)
            self.assertIn("risk=before_delivery", rows[key]["url"])
            self.assertEqual(self.order_ids(self.client.get(rows[key]["url"])), {order.pk}, key)
        self.assertEqual(sum(row["count"] for row in rows.values()), money["before_delivery_count"])
        self.assertContains(response, "未交車・尾款待收（刷卡）")

    def test_awaiting_payout_split_shows_installment_and_platform(self):
        installment = self.store_order("completed", payment_type="installment")
        platform = self.make_platform("completed")
        for order in (installment, platform):
            PaymentRecord.objects.create(order=order, receipt_kind="lender", expected_amount=500, received_amount=0)
            self.settle(order)
        response, money = self.money()
        rows = self.split(money, "awaiting_payout")
        self.assertEqual(list(rows), KEYS)     # T-284 追加：現金、刷卡 0 張也列，和另外兩格同一列
        for key, order in (("installment", installment), ("platform", platform)):
            self.assertEqual(rows[key]["count"], 1, key)
            self.assertIn("risk=awaiting_payout", rows[key]["url"])
            self.assertEqual(self.order_ids(self.client.get(rows[key]["url"])), {order.pk}, key)
        self.assertEqual(sum(row["count"] for row in rows.values()), money["awaiting_payout_count"])

    def test_awaiting_payout_lists_cash_when_it_happens(self):
        # 現金單有撥款列（例如人工建立）也要算得到，張數才會和合計對得上。
        cash = self.store_order("completed")
        PaymentRecord.objects.create(order=cash, receipt_kind="lender", expected_amount=500, received_amount=0)
        self.settle(cash)
        _response, money = self.money()
        rows = self.split(money, "awaiting_payout")
        self.assertEqual(list(rows), KEYS)
        self.assertEqual(rows["cash"]["count"], 1)

    # ── 撥款待入帳 ──

    def test_reconciliation_split_by_channel(self):
        installment = self.make_order(payment_type="installment", installment_amount=Decimal("60000"),
                                      installment_company="測試分期", installment_periods=24, cash_receivable_v2=True,
                                      payment_splits=[{"method": "cash", "amount": 19800},
                                                      {"method": "installment", "amount": 60000}])
        platform = self.make_order(source_type="platform", source=self.platform, vehicle_price=Decimal("0"),
                                   plate_insurance_fee=Decimal("2100"))
        PaymentRecord.objects.create(order=installment, receipt_kind="lender", expected_amount=500, received_amount=0)
        attention = self.attention()
        self.assertNotIn("reconciliation", attention)
        for key, order, label in (("installment", installment, "分期撥款待入帳"), ("platform", platform, "平台撥款待入帳")):
            item = attention[f"reconciliation_{key}"]
            self.assertEqual(item["label"], label)
            self.assertEqual(item["value"], 1, key)
            self.assertIn(f"channel={key}", item["url"])
            response = self.follow(item)
            self.assertEqual({row.order_id for row in response.context["page_obj"].paginator.object_list}, {order.pk})
        report = self.client.get(reverse("operations_report"))
        recon = report.context["cockpit"]["reconciliation"]
        self.assertEqual(sum(row["pending"] for row in recon["channels"]), recon["pending"])

    # ── 不拆的列與權限 ──

    def test_order_list_without_pay_is_unchanged_and_pay_is_labelled(self):
        orders = self.categorized()
        for order in orders.values():
            self.owing(order)
        plain = self.order_ids(self.client.get(reverse("order_list"), {"risk": "unsettled_delivered"}))
        self.assertEqual(plain, {order.pk for order in orders.values()})
        response = self.client.get(reverse("order_list"), {"risk": "unsettled_delivered", "pay": "card"})
        self.assertEqual(self.order_ids(response), {orders["card"].pk})
        self.assertContains(response, "付款方式「刷卡」")

    def test_split_amounts_hidden_without_operations(self):
        self.owing(self.store_order("completed"))
        data = operations_cockpit.build("month", self.today)
        flags = {"dashboard": True, "operations": False, "profit": False, "reconciliation": False,
                 "dealer_payouts": False, "incentives": False,
                 "links": {"order_list": True, "reconciliation_list": False, "inventory_list": False,
                           "dealer_payout_list": False, "incentive_rule_list": False}}
        view = operations_cockpit.for_viewer(data, flags)
        for bucket in view["money"]["split"].values():
            for row in bucket:
                self.assertIsNone(row.get("amount"))
