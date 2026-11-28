"""T-338：訂單頁成本卡的 3 個自動儲存同類問題（接續 T-331）。

1. 成本卡下方的黃色提示「目前找不到符合此車型與領牌日期的成本規則…」跟著自動儲存換新（vehicle_cost_warning_html）。
2. 依規則帶入的成本在收支改了金額：清掉 vehicle_cost_rule，卡片顯示「人工輸入」，重新整理後一致。
3. 收支「改回依規則計算」：重新套用成本規則，卡片恢復依規則計算的顯示；按鈕本身也跟著自動儲存換新。

三項都只動車輛成本與它的來源；淨利、應收、傭金、交車照既有計算，另外斷言。
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import OrderChange, OrderOperationsProfile
from sales.services.finance_ledger import finance_totals
from sales.services.payment_summary import payment_summary
from sales.tests import test_order_flow as flow
from sales.tests import test_vehicle_cost_card_t331 as t331
from sales.tests.test_vehicle_cost_card_t331 import MANUAL_NOTE, MANUAL_TAG

WARNING_TEXT = "目前找不到符合此車型與領牌日期的成本規則，補建前無法完成領牌。"
WARNING_PLACEHOLDER = "<template data-vehicle-cost-warning></template>"
RESET_PLACEHOLDER = "<template data-vehicle-cost-reset></template>"
RESET_BUTTON = '<button class="button ghost small" type="submit" form="vehicle-cost-reset-form">改回依規則計算</button>'


class VehicleCostAutosaveT338Tests(TestCase):
    setUp = flow.OrderFlowTests.setUp
    make_order = flow.OrderFlowTests.make_order
    prepare = t331.VehicleCostCardAutosaveTests.prepare
    operations_post = t331.VehicleCostCardAutosaveTests.operations_post
    card_on_page = t331.VehicleCostCardAutosaveTests.card_on_page

    # ---------------------------------------------------------------- 共用

    def page(self, order):
        return self.client.get(reverse("order_detail", args=[order.pk])).content.decode()

    def marked(self, page, marker, closing):
        """頁面上帶 marker 的那個元素（含空位 template）。"""
        start = page.index(marker)
        begin = page.rindex("<", 0, start)
        if page[begin:].startswith("<template"):
            return page[begin:page.index("</template>", start) + len("</template>")]
        return page[begin:page.index(closing, start) + len(closing)]

    def warning_on_page(self, order):
        return self.marked(self.page(order), "data-vehicle-cost-warning", "</div>")

    def reset_on_page(self, order):
        return self.marked(self.page(order), "data-vehicle-cost-reset", "</p>")

    def reset_post(self, order, **overrides):
        order.refresh_from_db()
        profile = OrderOperationsProfile.objects.get(order=order)
        data = {"_order_revision": str(order.revision),
                "operations-financial_revision": profile.updated_at.isoformat(), **overrides}
        return self.client.post(reverse("order_vehicle_cost_reset", args=[order.pk]), data,
                                HTTP_X_ORDER_WORKSPACE="1", HTTP_ACCEPT="application/json")

    def figures(self, order):
        """不該被成本來源影響的計算：應收、傭金、交車條件（淨利另外依成本差額斷言）。"""
        order.refresh_from_db()
        profile = OrderOperationsProfile.objects.get(order=order)
        return {
            "customer_receivable_total": order.customer_receivable_total,
            "customer_balance_due": order.customer_balance_due,
            "dealer_commission_expense": profile.dealer_commission_expense,
            "delivery_blockers": order.delivery_blockers(payment_summary(order)),
        }

    def net_profit(self, order):
        profile = OrderOperationsProfile.objects.get(order=order)
        self.assertEqual(profile.net_profit, finance_totals(profile)["net"])
        return profile.net_profit

    # ---------------------------------------------------------------- 1. 黃色提示

    def missing_rule_order(self):
        """預計領牌日早於成本規則生效日：找不到規則、成本 0，頁面顯示黃色提示。"""
        order = self.prepare(vehicle_cost=Decimal("0"), vehicle_cost_rule=None, vehicle_cost_manual=False,
                             vehicle_cost_registration_date=None, manual_financial_fields=[])
        type(order).objects.filter(pk=order.pk).update(registration_date=date(2025, 6, 1))
        return order

    def test_warning_disappears_when_cost_typed(self):
        order = self.missing_rule_order()
        self.assertIn(WARNING_TEXT, self.warning_on_page(order))
        response = self.operations_post(order, vehicle_cost="59000")
        self.assertEqual(response.status_code, 200, response.content)
        html = response.json()["vehicle_cost_warning_html"]
        self.assertEqual(html.strip(), WARNING_PLACEHOLDER)
        # 重新整理後一致。
        self.assertEqual(self.warning_on_page(order), html.strip())

    def test_warning_returned_while_rule_still_missing(self):
        order = self.missing_rule_order()
        response = self.operations_post(order, shipping_expense="800")
        self.assertEqual(response.status_code, 200, response.content)
        html = response.json()["vehicle_cost_warning_html"]
        self.assertIn('<div class="message warning" data-vehicle-cost-warning>', html)
        self.assertIn(WARNING_TEXT, html)
        self.assertEqual(self.warning_on_page(order), html.strip())

    def test_failed_autosave_returns_no_warning_or_reset(self):
        order = self.missing_rule_order()
        response = self.operations_post(order, vehicle_cost="59000", financial_revision="stale")
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("vehicle_cost_warning_html", response.json())
        self.assertNotIn("vehicle_cost_reset_html", response.json())

    # ---------------------------------------------------------------- 2. 改成本清掉規則

    def test_editing_rule_cost_clears_rule_and_shows_manual(self):
        order = self.prepare()
        profile = OrderOperationsProfile.objects.get(order=order)
        self.assertEqual(profile.vehicle_cost_rule, self.settlement_rule)
        self.assertIn("ledger-tag--estimate", self.card_on_page(order))
        before, profit_before = self.figures(order), self.net_profit(order)

        response = self.operations_post(order, vehicle_cost="58800")
        self.assertEqual(response.status_code, 200, response.content)
        profile.refresh_from_db()
        self.assertIsNone(profile.vehicle_cost_rule)
        self.assertIsNone(profile.vehicle_cost_registration_date)
        self.assertTrue(profile.vehicle_cost_manual)
        self.assertIn("vehicle_cost", profile.manual_financial_fields)
        self.assertEqual(profile.vehicle_cost, Decimal("58800"))

        html = response.json()["vehicle_cost_card_html"]
        self.assertIn(MANUAL_TAG, html)
        self.assertIn(MANUAL_NOTE, html)
        self.assertNotIn("依訂單日", html)
        self.assertEqual(self.card_on_page(order), html.strip())
        # 人工輸入不會被誤報找不到規則。
        self.assertEqual(response.json()["vehicle_cost_warning_html"].strip(), WARNING_PLACEHOLDER)

        # 淨利只差成本的差額；應收、傭金、交車不變。
        self.assertEqual(self.net_profit(order), profit_before + Decimal("1200"))
        self.assertEqual(self.figures(order), before)

    def test_manual_cost_survives_later_autosave_and_registration_refresh(self):
        """清掉規則後，其他欄位的自動儲存、重算成本都不會把人工金額蓋回規則金額。"""
        from sales.services.settlement_cost import apply_order_settlement_cost
        order = self.prepare()
        self.operations_post(order, vehicle_cost="58800")
        self.operations_post(order, shipping_expense="500")
        apply_order_settlement_cost(order)
        profile = OrderOperationsProfile.objects.get(order=order)
        self.assertEqual(profile.vehicle_cost, Decimal("58800"))
        self.assertIsNone(profile.vehicle_cost_rule)
        self.assertIn(MANUAL_TAG, self.card_on_page(order))

    # ---------------------------------------------------------------- 3. 改回依規則計算

    def test_reset_button_follows_autosave(self):
        order = self.prepare()
        # 依規則計算時不顯示按鈕，只留空位。
        self.assertEqual(self.reset_on_page(order), RESET_PLACEHOLDER)
        self.assertIn('id="vehicle-cost-reset-form"', self.page(order))
        response = self.operations_post(order, vehicle_cost="58800")
        html = response.json()["vehicle_cost_reset_html"]
        self.assertIn(RESET_BUTTON, html)
        self.assertIn("成本規則 $60,000（尚未領牌，依訂單日）", html)
        self.assertEqual(self.reset_on_page(order), html.strip())

    def test_reset_restores_rule_cost(self):
        order = self.prepare()
        before, profit_rule = self.figures(order), self.net_profit(order)
        self.operations_post(order, vehicle_cost="58800")

        response = self.reset_post(order)
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["message"], "已改回依規則計算，車輛成本 $60,000。")
        profile = OrderOperationsProfile.objects.get(order=order)
        self.assertEqual(profile.vehicle_cost, Decimal("60000"))
        self.assertEqual(profile.vehicle_cost_rule, self.settlement_rule)
        self.assertFalse(profile.vehicle_cost_manual)
        self.assertNotIn("vehicle_cost", profile.manual_financial_fields)
        self.assertIsNone(profile.vehicle_cost_locked_at)
        # 收支欄位跟著同步成規則金額。
        self.assertEqual(payload["sync"]["operations"]["operations-vehicle_cost"], "60000")

        card = payload["vehicle_cost_card_html"]
        self.assertIn('<span class="ledger-tag ledger-tag--estimate">預估</span>', card)
        self.assertIn("尚未領牌，依訂單日", card)
        self.assertNotIn(MANUAL_TAG, card)
        self.assertEqual(self.card_on_page(order), card.strip())
        self.assertEqual(payload["vehicle_cost_reset_html"].strip(), RESET_PLACEHOLDER)
        self.assertEqual(self.reset_on_page(order), RESET_PLACEHOLDER)
        self.assertEqual(payload["vehicle_cost_warning_html"].strip(), WARNING_PLACEHOLDER)
        # 收支來源標籤回到系統帶入。
        self.assertIn('data-ledger-source="system"', self.ledger_row(order))

        change = OrderChange.objects.filter(order=order, reason="車輛成本改回依規則計算").get()
        self.assertEqual(change.changes, {"vehicle_cost": {"before": "58800", "after": "60000"}})
        # 淨利回到依規則的金額；應收、傭金、交車不變。
        self.assertEqual(self.net_profit(order), profit_rule)
        self.assertEqual(self.figures(order), before)

    def ledger_row(self, order):
        page = self.page(order)
        field = page.index('name="operations-vehicle_cost"')
        return page[page.rindex('data-ledger-row', 0, field) - 40:field]

    def test_reset_on_confirmed_registration_locks_again(self):
        """已確認領牌的單：改回規則依領牌日套用，並和確認領牌時一樣固定。"""
        order = self.prepare(vehicle_cost=Decimal("55000"), vehicle_cost_rule=None, vehicle_cost_manual=True,
                             manual_financial_fields=["vehicle_cost"], vehicle_cost_locked_at=timezone.now())
        type(order).objects.filter(pk=order.pk).update(registration_date=date(2026, 3, 1),
                                                     registration_completed_at=timezone.now())
        self.assertIn("成本規則 $60,000（依領牌日）", self.reset_on_page(order))
        before = self.figures(order)
        response = self.reset_post(order)
        self.assertEqual(response.status_code, 200, response.content)
        profile = OrderOperationsProfile.objects.get(order=order)
        self.assertEqual(profile.vehicle_cost, Decimal("60000"))
        self.assertEqual(profile.vehicle_cost_registration_date, date(2026, 3, 1))
        self.assertIsNotNone(profile.vehicle_cost_locked_at)
        self.assertEqual(profile.vehicle_cost_locked_by, self.user.get_username())
        card = response.json()["vehicle_cost_card_html"]
        self.assertIn('<span class="ledger-tag ledger-tag--locked">已確認</span>', card)
        self.assertIn("依領牌日 2026/03/01", card)
        self.assertEqual(self.card_on_page(order), card.strip())
        self.assertEqual(self.figures(order), before)

    def test_reset_without_rule_is_refused(self):
        order = self.prepare(vehicle_cost=Decimal("55000"), vehicle_cost_rule=None, vehicle_cost_manual=True,
                             manual_financial_fields=["vehicle_cost"])
        self.settlement_rule.delete()
        self.assertEqual(self.reset_on_page(order), RESET_PLACEHOLDER)
        response = self.reset_post(order)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        profile = OrderOperationsProfile.objects.get(order=order)
        self.assertEqual(profile.vehicle_cost, Decimal("55000"))
        self.assertTrue(profile.vehicle_cost_manual)

    def test_reset_with_stale_revision_is_refused(self):
        order = self.prepare(vehicle_cost=Decimal("55000"), vehicle_cost_rule=None, vehicle_cost_manual=True,
                             manual_financial_fields=["vehicle_cost"])
        response = self.reset_post(order, **{"operations-financial_revision": "stale"})
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("vehicle_cost_card_html", response.json())
        self.assertEqual(OrderOperationsProfile.objects.get(order=order).vehicle_cost, Decimal("55000"))

    def test_reset_only_accepts_workspace_post(self):
        order = self.prepare(vehicle_cost=Decimal("55000"), vehicle_cost_rule=None, vehicle_cost_manual=True,
                             manual_financial_fields=["vehicle_cost"])
        url = reverse("order_vehicle_cost_reset", args=[order.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertRedirects(self.client.post(url, {}), reverse("order_detail", args=[order.pk]),
                             fetch_redirect_response=False)
        self.assertEqual(OrderOperationsProfile.objects.get(order=order).vehicle_cost, Decimal("55000"))
