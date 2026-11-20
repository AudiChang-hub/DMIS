"""T-258：第 5 步「車行獎勵」卡第一列列出傭金（與收入與支出同一欄），下面接活動獎勵；台數獎金不列。"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from sales.models import DealerRewardCampaign, OrderOperationsProfile, SalesOrder, SalesSource
from sales.services.dealer_commission import apply_order_dealer_commission
from sales.tests import test_incentive_campaigns as campaigns


class DealerRewardCommissionCardTests(campaigns.CampaignFixtureMixin, TestCase):
    """沿用領牌流程測試的車型、原廠活動、甲車行與兩個車行獎勵活動（機油限甲車行、禮券全車行）。"""
    setUp_fixtures = campaigns.RegistrationFlowTests.setUp
    order_with_vehicle = campaigns.RegistrationFlowTests.order_with_vehicle
    save_registration = campaigns.RegistrationFlowTests.save_registration

    def setUp(self):
        self.setUp_fixtures()
        self.model.base_dealer_commission = Decimal("1500")
        self.model.save(update_fields=["base_dealer_commission"])

    def card(self, order):
        page = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "registration"}).content.decode()
        if "data-order-dealer-rewards" not in page:
            return None
        return page.split("data-order-dealer-rewards", 1)[1].split("</section>", 1)[0]

    def ledger_value(self, order):
        page = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "finance"}).content.decode()
        tag = page.split('name="operations-dealer_commission_expense"', 1)[1].split(">", 1)[0]
        return tag.split('value="', 1)[1].split('"', 1)[0]

    def test_commission_and_campaign_rewards_with_separate_states(self):
        order = self.order_with_vehicle(source=self.dealer_a, source_type=SalesOrder.SourceType.DEALER)
        self.save_registration(order, "2026-11-20")
        profile = OrderOperationsProfile.objects.get(order=order)
        self.assertEqual(profile.dealer_commission_expense, Decimal("1500"))
        card = self.card(order)
        commission, rewards = card.split("data-dealer-reward-lines", 1)
        # 傭金在第一列，金額與第 6 步支出區同一欄。
        self.assertIn("<dt>傭金", commission)
        self.assertIn("$1,500", commission)
        self.assertEqual(self.ledger_value(order), "1500")
        self.assertIn("ledger-tag--locked\">已固定", commission)
        self.assertIn("機油", rewards)
        self.assertIn("禮券", rewards)
        self.assertNotIn("台數獎金", card)
        # 傭金改成人工輸入後，傭金與活動獎勵各自標示，不混用。
        profile.dealer_commission_expense = Decimal("1800")
        profile.manual_financial_fields = sorted(set(profile.manual_financial_fields or []) | {"dealer_commission_expense"})
        profile.save()
        card = self.card(order)
        commission, rewards = card.split("data-dealer-reward-lines", 1)
        self.assertIn("ledger-tag--manual\">人工輸入", commission)
        self.assertIn("$1,800", commission)
        self.assertNotIn("人工輸入", rewards)
        self.assertIn("ledger-tag--locked\">已固定", rewards)
        self.assertEqual(self.ledger_value(order), "1800")

    def test_commission_only_shows_card_with_estimate(self):
        DealerRewardCampaign.objects.all().delete()
        order = self.order_with_vehicle(source=self.dealer_a, source_type=SalesOrder.SourceType.DEALER)
        apply_order_dealer_commission(order)
        card = self.card(order)
        self.assertIsNotNone(card, "只有傭金也要顯示車行獎勵卡")
        self.assertIn("<dt>傭金", card)
        self.assertIn("ledger-tag--estimate\">預估", card)
        self.assertIn("給 甲車行", card)
        self.assertNotIn("data-dealer-reward-lines", card)

    def test_campaign_rewards_only_has_no_commission_row(self):
        self.model.base_dealer_commission = Decimal("0")
        self.model.save(update_fields=["base_dealer_commission"])
        order = self.order_with_vehicle(source=self.dealer_a, source_type=SalesOrder.SourceType.DEALER)
        self.save_registration(order, "2026-11-20")
        self.assertEqual(OrderOperationsProfile.objects.get(order=order).dealer_commission_expense, 0)
        card = self.card(order)
        self.assertIsNotNone(card)
        self.assertNotIn("data-dealer-commission", card)
        self.assertNotIn("<dt>傭金", card)
        self.assertIn("機油", card)

    def test_platform_order_never_lists_commission(self):
        platform = SalesSource.objects.create(name="示範平台", source_type="platform")
        order = self.order_with_vehicle(source=platform, source_type=SalesOrder.SourceType.PLATFORM)
        self.save_registration(order, "2026-11-20", plate="XYZ-0001")
        profile = OrderOperationsProfile.objects.get(order=order)
        profile.dealer_commission_expense = Decimal("800")
        profile.manual_financial_fields = sorted(set(profile.manual_financial_fields or []) | {"dealer_commission_expense"})
        profile.save()
        # 平台單沒有車行獎勵、也不列傭金：整張卡不顯示（支出區仍照舊列傭金支出）。
        self.assertIsNone(self.card(order))
        self.assertEqual(self.ledger_value(order), "800")

    def test_no_commission_and_no_rewards_hides_card(self):
        DealerRewardCampaign.objects.all().delete()
        self.model.base_dealer_commission = Decimal("0")
        self.model.save(update_fields=["base_dealer_commission"])
        order = self.order_with_vehicle(source=self.dealer_a, source_type=SalesOrder.SourceType.DEALER)
        self.save_registration(order, "2026-11-20")
        self.assertIsNone(self.card(order))
