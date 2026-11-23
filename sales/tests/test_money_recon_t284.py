"""T-284（使用者 2026-11-23 選 A）：營運總表「錢」的撥款待入帳兩列不再像待收合計的加項。

- 兩列移到待收合計下方，小標「其中：撥款待入帳（已含在上面三格）」，每列寫出對回三格的哪幾格。
- 撥款待入帳（對帳佇列 confirmed=False）和三格（money_bucket）範圍不同：對帳佇列含取消單、分期金額是未入帳列的
  預計金額；三格是 lender_due。加總相同才寫「＝」，不同就寫出差額，不寫對不上的等式。
- 未交車・尾款待收的拆列寫出金額怎麼組成：撥款＋客人。
- 沒有 operations 權限的人看不到金額。
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from sales.models import OrderOperationsProfile, PaymentRecord, SalesOrder, ScreenAccessGrant, UserAccessState
from sales.services.payment_summary import payment_summary
from sales.tests.test_money_card_t278 import ZERO, MoneyCardTestBase


class ReconciliationTermsTests(MoneyCardTestBase):
    def installment(self, status, amount, settle=False):
        order = self.order(status, timezone.now() if status == "completed" else None, source_type="store",
                           source=self.staff, payment_type="installment")
        self.lender_pending(order, amount)
        return self.settle(order) if settle else order

    def platform_order(self, status, estimate):
        order = self.order(status, timezone.now() if status == "completed" else None, source_type="platform",
                           source=self.platform, vehicle_price=Decimal("0"))
        self.settle(order)
        OrderOperationsProfile.objects.filter(order=order).update(actual_disbursement=estimate)
        return order

    def production_like(self):
        """正式站 2026-11-23 的形狀：已交車待撥款分期 1、平台 1；未交車分期（客人還有尾款）、現金。"""
        self.installment("completed", 86136, settle=True)
        self.before = self.installment("delivery_pending", 188160)
        self.platform_order("completed", Decimal("61277"))
        self.order("delivery_pending", source_type="store", source=self.staff)

    def channels(self, cockpit):
        return {row["key"]: row for row in cockpit["reconciliation"]["channels"]}

    def test_each_channel_adds_up_to_the_three_cells(self):
        self.production_like()
        response, cockpit = self.cockpit()
        rows = self.channels(cockpit)
        installment, platform = rows["installment"], rows["platform"]
        self.assertTrue(cockpit["reconciliation"]["matches"])
        self.assertEqual([(term["label"], term["count"], term["amount"]) for term in installment["card_terms"]],
                         [("未交車・分期", 1, Decimal("188160")), ("已交車待撥款・分期", 1, Decimal("86136"))])
        self.assertEqual(sum(term["count"] for term in installment["card_terms"]), installment["pending"])
        self.assertEqual(sum((term["amount"] for term in installment["card_terms"]), ZERO), installment["expected"])
        # 已交車／交車前兩邊各自對回一格（原本的「已交車 N・$／交車前 N・$」）。
        self.assertEqual(installment["card_terms"][1]["amount"], installment["delivered"]["expected"])
        self.assertEqual(installment["card_terms"][0]["amount"], installment["before"]["expected"])
        awaiting = {row["key"]: row for row in cockpit["money"]["split"]["awaiting_payout"]}
        self.assertEqual(installment["card_terms"][1]["amount"], awaiting["installment"]["amount"])
        # 分期撥款待入帳＝三格裡分期那幾格的撥款相加（直接從拆列算，不經 card_terms）。
        split = cockpit["money"]["split"]
        self.assertEqual(sum((row["payout"] for bucket in split.values() for row in bucket
                              if row["key"] == "installment"), ZERO), installment["expected"])
        self.assertEqual(sum(row["payout_count"] for bucket in split.values() for row in bucket
                             if row["key"] == "installment"), installment["pending"])
        self.assertEqual([(term["label"], term["count"], term["amount"], term["estimated"])
                          for term in platform["card_terms"]],
                         [("已交車待撥款・平台", 1, Decimal("61277"), True)])
        self.assertEqual((platform["pending"], platform["expected"]), (1, awaiting["platform"]["amount"]))
        self.assertContains(response, "其中：撥款待入帳（已含在上面三格）")
        self.assertContains(response, "<span>＝未交車・分期 1 張的撥款 $188,160</span>"
                                      "<span>＋已交車待撥款・分期 1 張 $86,136</span>")
        self.assertContains(response, "<span>＝已交車待撥款・平台 1 張 預估 $61,277</span>")
        self.assertNotContains(response, "對帳佇列多")
        self.assertNotContains(response, "對帳佇列少")

    def test_before_delivery_installment_cell_shows_payout_and_customer(self):
        self.production_like()
        response, cockpit = self.cockpit()
        cells = {row["key"]: row for row in cockpit["money"]["split"]["before_delivery"]}
        cell = cells["installment"]
        customer = payment_summary(SalesOrder.objects.get(pk=self.before.pk))["customer_due"]
        self.assertGreater(customer, 0)
        self.assertEqual((cell["payout"], cell["customer"]), (Decimal("188160"), customer))
        self.assertEqual(cell["payout"] + cell["customer"], cell["amount"])
        for row in cells.values():
            self.assertEqual(row["payout"] + row["customer"], row["amount"], row["key"])
        self.assertContains(response, '<span class="ops-split__part">撥款 $188,160</span>'
                                      f'<span class="ops-split__part">＋客人 ${customer:,.0f}</span></small>')
        # 現金那格沒有撥款，不寫組成；其他兩格不用 parts。
        self.assertEqual(response.content.decode().count("data-split-parts"), 1)

    def test_section_sits_below_total_and_formula(self):
        self.production_like()
        response, _cockpit = self.cockpit()
        html = response.content.decode()
        total = html.index("待收合計（")
        formula = html.index("data-outstanding-formula")
        section = html.index('id="ops-recon-title"')
        credit = html.index("車行未付<span")
        self.assertLess(total, formula)
        self.assertLess(formula, section)
        self.assertLess(section, html.index("分期撥款待入帳</th>"))
        self.assertLess(html.index("平台撥款待入帳</th>"), credit)

    def test_cancelled_order_in_queue_shows_gap_not_equation(self):
        # 對帳佇列不看訂單狀態：取消單留下的未入帳撥款列照樣列，三格不算取消單。
        self.production_like()
        cancelled = self.installment("completed", 14000, settle=True)
        SalesOrder.all_objects.filter(pk=cancelled.pk).update(status="cancel_refund_pending")
        response, cockpit = self.cockpit()
        row = self.channels(cockpit)["installment"]
        self.assertFalse(row["matches"])
        self.assertFalse(cockpit["reconciliation"]["matches"])
        self.assertEqual(row["gap"], {"count": 1, "count_more": True, "amount": Decimal("14000"), "amount_more": True})
        card = sum((term["amount"] for term in row["card_terms"]), ZERO)
        self.assertEqual(card + row["gap"]["amount"], row["expected"])
        self.assertEqual(sum(term["count"] for term in row["card_terms"]) + row["gap"]["count"], row["pending"])
        self.assertContains(response, "撥款待入帳（和上面三格對不上的地方寫在各列）")
        self.assertNotContains(response, "已含在上面三格")
        self.assertContains(response, "<span>上面三格裡是</span><span>未交車・分期 1 張的撥款 $188,160</span>"
                                      "<span>＋已交車待撥款・分期 1 張 $86,136</span>")
        self.assertContains(response, ">對帳佇列多 1 張、金額多 $14,000，到對帳頁核對</span>")
        self.assertTrue(self.channels(cockpit)["platform"]["matches"])

    def test_partly_posted_payout_shows_amount_gap(self):
        # 分期撥款分兩筆、第一筆入帳金額和預計不同：對帳佇列是未入帳那筆的預計，三格是應撥減已入帳。
        order = self.order("completed", timezone.now(), source_type="store", source=self.staff,
                           payment_type="installment")
        PaymentRecord.objects.create(order=order, receipt_kind="lender", expected_amount=50000, received_amount=48000,
                                     confirmed=True)
        self.lender_pending(order, 36000)
        self.settle(order)
        response, cockpit = self.cockpit()
        row = self.channels(cockpit)["installment"]
        self.assertEqual((row["pending"], row["expected"]), (1, Decimal("36000")))
        self.assertEqual([(term["count"], term["amount"]) for term in row["card_terms"]], [(1, Decimal("38000"))])
        self.assertEqual(row["gap"], {"count": 0, "count_more": False, "amount": Decimal("2000"), "amount_more": False})
        self.assertContains(response, ">對帳佇列金額少 $2,000，到對帳頁核對</span>")

    def test_cell_with_some_orders_without_payout_says_which(self):
        self.installment("delivery_pending", 188160)
        PaymentRecord.objects.create(order=self.installment("delivery_pending", 100000), receipt_kind="lender",
                                     expected_amount=0, received_amount=100000, confirmed=True)
        response, cockpit = self.cockpit()
        cell = {row["key"]: row for row in cockpit["money"]["split"]["before_delivery"]}["installment"]
        self.assertEqual((cell["count"], cell["payout_count"]), (2, 1))
        row = self.channels(cockpit)["installment"]
        self.assertEqual([(term["of"], term["count"]) for term in row["card_terms"]], [(2, 1)])
        self.assertContains(response, "未交車・分期 2 張中 1 張的撥款 $188,160")

    def test_viewer_without_operations_sees_counts_only(self):
        self.production_like()
        user = get_user_model().objects.create_user("t284-recon", password="test-only")
        UserAccessState.objects.create(user=user, configured=True)
        for key in ("dashboard", "reconciliation"):
            ScreenAccessGrant.objects.create(user=user, screen_key=key, view=True)
        self.client.force_login(user)
        response = self.client.get(reverse("operations_report"))
        cockpit = response.context["cockpit"]
        rows = self.channels(cockpit)
        self.assertTrue(all(term["amount"] is None for row in rows.values() for term in row["card_terms"]))
        self.assertTrue(all(row["matches"] for row in rows.values()))
        cells = cockpit["money"]["split"]["before_delivery"]
        self.assertTrue(all(row["payout"] is None and row["customer"] is None for row in cells))
        self.assertContains(response, "<span>＝未交車・分期 1 張的撥款</span><span>＋已交車待撥款・分期 1 張</span>")
        self.assertNotContains(response, "data-split-parts")
        for amount in ("86,136", "188,160", "61,277"):
            self.assertNotContains(response, amount)


class SplitRowOrderTests(MoneyCardTestBase):
    """T-284 追加（使用者 2026-11-23）：三格的付款方式都固定列現金→刷卡→分期→平台，0 張也列，橫著看同一列。"""

    def test_three_cells_list_same_four_rows_in_same_order(self):
        order = self.order("completed", timezone.now(), source_type="store", source=self.staff,
                           payment_type="installment")
        self.settle(self.lender_pending(order, 86136))                    # 只有已交車待撥款・分期有單
        response, cockpit = self.cockpit()
        split = cockpit["money"]["split"]
        expected = ["cash", "card", "installment", "platform"]
        self.assertEqual(list(split), ["unsettled", "before_delivery", "awaiting_payout"])
        for bucket, rows in split.items():
            self.assertEqual([row["key"] for row in rows], expected, bucket)
        awaiting = {row["key"]: row for row in split["awaiting_payout"]}
        self.assertEqual([awaiting[key]["count"] for key in expected], [0, 0, 1, 0])
        self.assertEqual(awaiting["installment"]["amount"], Decimal("86136"))
        self.assertIn("risk=awaiting_payout", awaiting["installment"]["url"])
        html = response.content.decode()
        lists = html.split('<ul class="ops-split"')[1:]
        self.assertEqual(len(lists), 3)
        for chunk in lists:
            chunk = chunk.split("</ul>")[0]
            positions = [chunk.index(f"<span>{label}</span>") for label in ("現金", "刷卡", "分期", "平台")]
            self.assertEqual(positions, sorted(positions))
        # 0 張的列照樣顯示 0、不給連結（模板只在有張數時連）。
        self.assertContains(response, '<li class="is-zero" title="已交車待撥款（現金）"><span>現金</span><b aria-hidden="true">—</b><span class="ops-visually-hidden">0 張</span></li>')
