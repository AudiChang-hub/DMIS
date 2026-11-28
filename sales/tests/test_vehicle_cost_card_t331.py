"""T-331：訂單頁領牌步驟的「車輛結算成本」卡跟著自動儲存更新，不必重新整理。

收支改了車輛成本、自動儲存成功後，回應帶 vehicle_cost_card_html（與頁面同一份 partial），
前端（order-workspace.js）把畫面上的 [data-vehicle-cost-card] 換成新版；儲存失敗不回這份 HTML，卡片維持原值。
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from sales.forms import OrderOperationsForm, PaymentRecordFormSet
from sales.models import OrderOperationsProfile
from sales.tests import test_order_flow as flow
from sales.tests.test_order_workspace import form_data, formset_data

MANUAL_NOTE = "已有適用的成本規則；這筆是人工輸入，不依規則覆蓋。"
MANUAL_TAG = '<span class="ledger-tag ledger-tag--manual">人工輸入</span>'


class VehicleCostCardAutosaveTests(TestCase):
    setUp = flow.OrderFlowTests.setUp
    make_order = flow.OrderFlowTests.make_order

    def prepare(self, **profile_values):
        order = self.make_order()
        order.allocate(self.vehicle)
        profile, _ = OrderOperationsProfile.objects.get_or_create(order=order)
        if profile_values:
            OrderOperationsProfile.objects.filter(pk=profile.pk).update(**profile_values)
        self.client.force_login(self.user)
        return order

    def operations_post(self, order, **changes):
        order.refresh_from_db()
        data = {**form_data(OrderOperationsForm(instance=order.operations, prefix="operations")),
                **formset_data(PaymentRecordFormSet(instance=order, prefix="payments"))}
        data.update({f"operations-{name}": value for name, value in changes.items()})
        return self.client.post(reverse("order_operations", args=[order.pk]), data,
                                HTTP_X_ORDER_WORKSPACE="1", HTTP_ACCEPT="application/json")

    def card_on_page(self, order):
        page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        start = page.index("data-vehicle-cost-card")
        return page[page.rindex("<", 0, start):page.index("</section>", start) + len("</section>")]

    def test_manual_cost_autosave_returns_new_card(self):
        """畫面截圖的情況：人工輸入的成本再改一次，回應的卡片就是新金額、人工輸入標籤與說明。"""
        order = self.prepare(vehicle_cost=Decimal("60000"), vehicle_cost_rule=None, vehicle_cost_manual=True,
                             manual_financial_fields=["vehicle_cost"])
        response = self.operations_post(order, vehicle_cost="59980")
        self.assertEqual(response.status_code, 200, response.content)
        html = response.json()["vehicle_cost_card_html"]
        self.assertIn("data-vehicle-cost-card", html)
        self.assertIn("<dt>結算成本</dt><dd>$59,980</dd>", html)
        self.assertIn(MANUAL_TAG, html)
        self.assertIn(MANUAL_NOTE, html)
        self.assertNotIn("$60,000", html)
        # 與重新整理後的頁面同一份內容。
        self.assertEqual(self.card_on_page(order), html.strip())

    def test_rule_cost_autosave_updates_amount(self):
        """依規則帶入的成本改成人工金額，卡片金額立刻換成新值（與重新整理後一致）。"""
        order = self.prepare()
        self.assertIn("<dd>$60,000</dd>", self.card_on_page(order))
        response = self.operations_post(order, vehicle_cost="58800")
        self.assertEqual(response.status_code, 200, response.content)
        html = response.json()["vehicle_cost_card_html"]
        self.assertIn("<dt>結算成本</dt><dd>$58,800</dd>", html)
        self.assertEqual(self.card_on_page(order), html.strip())

    def test_back_to_rule_switches_card_back(self):
        """改回依規則計算後，下一次自動儲存的卡片換回規則顯示，不再標人工輸入。"""
        order = self.prepare(vehicle_cost=Decimal("59980"), vehicle_cost_rule=None, vehicle_cost_manual=True,
                             manual_financial_fields=["vehicle_cost"])
        OrderOperationsProfile.objects.filter(order=order).update(
            vehicle_cost=Decimal("60000"), vehicle_cost_rule=self.settlement_rule, vehicle_cost_manual=False,
            vehicle_cost_registration_date=order.order_date, manual_financial_fields=[])
        response = self.operations_post(order, shipping_expense="800")
        self.assertEqual(response.status_code, 200, response.content)
        html = response.json()["vehicle_cost_card_html"]
        self.assertIn("<dd>$60,000</dd>", html)
        self.assertIn("ledger-tag--estimate", html)
        self.assertNotIn(MANUAL_TAG, html)
        self.assertNotIn(MANUAL_NOTE, html)
        self.assertEqual(self.card_on_page(order), html.strip())

    def test_failed_autosave_returns_no_card(self):
        """儲存失敗不回卡片 HTML，前端保留原本的卡片。"""
        order = self.prepare()
        response = self.operations_post(order, vehicle_cost="59980", financial_revision="stale")
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("vehicle_cost_card_html", response.json())

    def test_hidden_card_keeps_placeholder(self):
        """還沒有成本可顯示時頁面留一個不佔版面的空位，之後出現成本也有地方換入。"""
        order = self.prepare(vehicle_cost=Decimal("0"), vehicle_cost_rule=None, vehicle_cost_manual=False,
                             manual_financial_fields=[])
        page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        self.assertIn('<template data-vehicle-cost-card></template>', page)
        self.assertNotIn('id="figure-vehicle-cost"', page)
        response = self.operations_post(order, vehicle_cost="59980")
        html = response.json()["vehicle_cost_card_html"]
        self.assertIn("<dd>$59,980</dd>", html)
        self.assertIn(MANUAL_TAG, html)
