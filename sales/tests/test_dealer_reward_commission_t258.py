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


class DealerRewardOverviewTests(campaigns.CampaignFixtureMixin, TestCase):
    """訂單總覽的「車行獎勵」區段：與第 5 步卡片同一份資料（傭金欄位＋車行獎勵明細）。"""
    setUp_fixtures = campaigns.RegistrationFlowTests.setUp
    order_with_vehicle = campaigns.RegistrationFlowTests.order_with_vehicle
    save_registration = campaigns.RegistrationFlowTests.save_registration

    def setUp(self):
        self.setUp_fixtures()
        self.model.base_dealer_commission = Decimal("1500")
        self.model.save(update_fields=["base_dealer_commission"])

    def section(self, overview):
        return next((section for section in overview["sections"] if section["key"] == "dealer_reward"), None)

    def rows(self, overview):
        return {row["label"]: row for row in self.section(overview)["rows"]}

    def test_overview_lists_commission_rewards_campaigns_and_states(self):
        from sales.services.order_overview import build_order_overview
        order = self.order_with_vehicle(source=self.dealer_a, source_type=SalesOrder.SourceType.DEALER)
        self.save_registration(order, "2026-11-20")
        order = SalesOrder.objects.get(pk=order.pk)
        SalesOrder.objects.filter(pk=order.pk).update(discount_internal_note="內部備註 NOTE257X")
        order.refresh_from_db()
        overview = build_order_overview(order)
        keys = [section["key"] for section in overview["sections"]]
        self.assertEqual(keys.index("dealer_reward"), keys.index("registration") + 1)
        rows = self.rows(overview)
        self.assertEqual((rows["傭金"]["value"], rows["傭金"]["copy"]), ("$1,500（已固定）", "1500"))
        self.assertEqual(rows["活動獎勵"]["value"], "機油 5 罐、禮券 1000 元（已固定）")
        self.assertEqual(rows["來源活動"]["value"], "四家車行 SUZUKI 油車送機油、全車行禮券")
        self.assertEqual(rows["活動獎勵給"]["value"], "甲車行")
        self.assertEqual(rows["傭金給"]["value"], "甲車行", "欄位列固定（T-292）：同車行也列")
        self.assertNotIn("台數獎金", str(self.section(overview)))
        # 「複製全部」涵蓋新列；T-257 的優惠備註仍不進總覽。
        self.assertIn("【車行獎勵】\n傭金：$1,500（已固定）\n活動獎勵：機油 5 罐、禮券 1000 元（已固定）\n"
                      "來源活動：四家車行 SUZUKI 油車送機油、全車行禮券", overview["plain_text"])
        self.assertNotIn("NOTE257X", str(overview))
        # 傭金改人工後與活動獎勵各自標示；與第 6 步同一欄。
        profile = OrderOperationsProfile.objects.get(order=order)
        profile.dealer_commission_expense = Decimal("1800")
        profile.manual_financial_fields = sorted(set(profile.manual_financial_fields or []) | {"dealer_commission_expense"})
        profile.save()
        order = SalesOrder.objects.get(pk=order.pk)
        rows = self.rows(build_order_overview(order))
        self.assertEqual(rows["傭金"]["value"], "$1,800（人工輸入）")
        self.assertTrue(rows["活動獎勵"]["value"].endswith("（已固定）"))
        # 頁面也有這一區（搜尋與複製都以資料列為單位）。
        page = self.client.get(reverse("order_overview", args=[order.pk]))
        self.assertContains(page, 'id="overview-dealer_reward"')
        self.assertContains(page, 'data-label="傭金" data-copy="1800"')

    def test_overview_without_finance_access_keeps_rewards_only(self):
        from sales.services.order_overview import build_order_overview
        order = self.order_with_vehicle(source=self.dealer_a, source_type=SalesOrder.SourceType.DEALER)
        self.save_registration(order, "2026-11-20")
        rows = self.rows(build_order_overview(SalesOrder.objects.get(pk=order.pk), include_finance=False))
        self.assertNotIn("傭金", rows)
        self.assertIn("活動獎勵", rows)

    def test_commission_only_overview_names_recipient(self):
        from sales.services.order_overview import build_order_overview
        DealerRewardCampaign.objects.all().delete()
        order = self.order_with_vehicle(source=self.dealer_a, source_type=SalesOrder.SourceType.DEALER)
        apply_order_dealer_commission(order)
        rows = self.rows(build_order_overview(SalesOrder.objects.get(pk=order.pk)))
        self.assertEqual(rows["傭金"]["value"], "$1,500（預估）")
        self.assertEqual(rows["傭金給"]["value"], "甲車行")
        self.assertEqual((rows["活動獎勵"]["value"], rows["活動獎勵"]["copy"]), ("—", ""))

    def test_platform_order_dealer_reward_section_is_blank(self):
        from sales.services.order_overview import build_order_overview
        platform = SalesSource.objects.create(name="示範平台", source_type="platform")
        order = self.order_with_vehicle(source=platform, source_type=SalesOrder.SourceType.PLATFORM)
        self.save_registration(order, "2026-11-20", plate="XYZ-0001")
        profile = OrderOperationsProfile.objects.get(order=order)
        profile.dealer_commission_expense = Decimal("800")
        profile.manual_financial_fields = ["dealer_commission_expense"]
        profile.save()
        overview = build_order_overview(SalesOrder.objects.get(pk=order.pk))
        # 區塊一律輸出（T-292）：平台單不列傭金，各列「—」、沒有複製值。
        self.assertTrue(self.section(overview)["rows"])
        self.assertTrue(all(row["value"] == "—" and row["copy"] == "" for row in self.section(overview)["rows"]))
        self.assertNotIn("【車行獎勵】", overview["plain_text"])
