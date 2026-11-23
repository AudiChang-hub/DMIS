"""T-282（使用者 2026-11-23）：營運總表「錢」的待收合計寫出怎麼組成，「交車前應收（正常）」改名「未交車・尾款待收」。

- 說明行：＝交車後未結清 N 張 $…＋（交車後未結清那幾張的撥款 $…）＋未交車・尾款待收 N 張 $…＋已交車待撥款 N 張 $…
- 張數加總＝outstanding_count、金額加總＝outstanding_amount；含平台預估的項目標「預估」。
- 沒有 operations 權限的人看不到金額，說明行也一樣（for_viewer）。
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from sales.models import OrderOperationsProfile, PaymentRecord, ScreenAccessGrant, UserAccessState
from sales.tests.test_money_card_t278 import ZERO, MoneyCardTestBase


class OutstandingFormulaTests(MoneyCardTestBase):
    def all_buckets(self):
        # 交車後未結清：平台單已交車、客人還沒付清，撥款部分（預估）另列。
        unsettled = self.order("completed", timezone.now(), source_type="platform", source=self.platform,
                               vehicle_price=Decimal("0"))
        OrderOperationsProfile.objects.filter(order=unsettled).update(actual_disbursement=Decimal("61277"))
        # 交車後未結清：本店現金單，客人只付了一部分。
        partial = self.order("completed", timezone.now(), source_type="store", source=self.staff)
        PaymentRecord.objects.create(order=partial, expected_amount=500, received_amount=100, confirmed=True)
        # 未交車・尾款待收：本店單一張、平台單一張（預估）。
        self.order("delivery_pending", source_type="store", source=self.staff)
        before_platform = self.order("delivery_pending", source_type="platform", source=self.platform,
                                     vehicle_price=Decimal("0"))
        self.settle(before_platform)
        OrderOperationsProfile.objects.filter(order=before_platform).update(actual_disbursement=Decimal("70000"))
        # 已交車待撥款：分期單客人已收清，只差分期撥款。
        self.settle(self.lender_pending(
            self.order("completed", timezone.now(), source_type="store", source=self.staff, payment_type="installment"),
            amount=72300))

    def test_terms_add_up_to_outstanding_count_and_amount(self):
        self.all_buckets()
        response, cockpit = self.cockpit()
        money = cockpit["money"]
        terms = money["outstanding_terms"]
        self.assertEqual([term["label"] for term in terms],
                         ["交車後未結清", "交車後未結清那幾張的撥款", "未交車・尾款待收", "已交車待撥款"])
        self.assertEqual(sum(term["count"] or 0 for term in terms), money["outstanding_count"])
        self.assertEqual(sum((term["amount"] for term in terms), ZERO), money["outstanding_amount"])
        self.assertEqual([term["count"] for term in terms], [2, None, 2, 1])
        self.assertEqual([term["estimated"] for term in terms], [False, True, True, False])
        # 名稱和卡片上方三格一致；含平台預估的項目標「預估」。
        for label in ("交車後未結清", "未交車・尾款待收", "已交車待撥款"):
            self.assertContains(response, f"<span>{label}")
        self.assertContains(response, f"<span>＋交車後未結清那幾張的撥款 預估 ${Decimal('61277'):,.0f}</span>")
        before = money["before_delivery_amount"]
        self.assertContains(response, f"<span>＋未交車・尾款待收 2 張 預估 ${before:,.0f}</span>")
        self.assertContains(response, "<span>＋已交車待撥款 1 張 $72,300</span>")
        self.assertContains(response, f"<span>＝交車後未結清 2 張 ${money['unsettled_amount']:,.0f}</span>")

    def test_no_unsettled_payout_term_when_zero(self):
        self.order("delivery_pending", source_type="store", source=self.staff)
        response, cockpit = self.cockpit()
        money = cockpit["money"]
        terms = money["outstanding_terms"]
        self.assertEqual([term["label"] for term in terms], ["交車後未結清", "未交車・尾款待收", "已交車待撥款"])
        self.assertEqual(sum(term["count"] for term in terms), money["outstanding_count"])
        self.assertEqual(sum((term["amount"] for term in terms), ZERO), money["outstanding_amount"])
        self.assertContains(response, "<span>＝交車後未結清 0 張 $0</span>")
        self.assertNotContains(response, "交車後未結清那幾張的撥款")

    def test_viewer_without_operations_gets_no_amounts(self):
        self.all_buckets()
        user = get_user_model().objects.create_user("t282-dashboard", password="test-only")
        UserAccessState.objects.create(user=user, configured=True)
        ScreenAccessGrant.objects.create(user=user, screen_key="dashboard", view=True)
        self.client.force_login(user)
        response = self.client.get(reverse("operations_report"))
        terms = response.context["cockpit"]["money"]["outstanding_terms"]
        self.assertEqual([term["label"] for term in terms], ["交車後未結清", "未交車・尾款待收", "已交車待撥款"])
        self.assertTrue(all(term["amount"] is None and not term["estimated"] for term in terms))
        self.assertEqual([term["count"] for term in terms], [2, 2, 1])
        self.assertNotContains(response, "data-outstanding-formula")
        self.assertNotContains(response, "72,300")
        self.assertNotContains(response, "61,277")
