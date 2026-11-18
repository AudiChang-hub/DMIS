"""T-225：建單（手動開單）後，原廠獎勵要依訂單成立日預先觸發（T-176），不必等之後改單才帶入。

根因：T-176 規定確認領牌前依訂單成立日預先觸發獎勵，但建單流程 `_create_intake_order` 只經
`sync_order_operations` 帶入預估成本與傭金，沒有呼叫 `apply_order_incentive_rule`；
新單要等到之後改單、改訂金或活動異動觸發 `refresh_unlocked_financials` 才會補上獎勵。
"""
import uuid
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from sales.models import DealerRewardCampaign, DealerRewardCampaignItem, SalesOrder
from sales.tests.campaign_helpers import make_campaign
from sales.tests.test_intake_deposit_discount import IntakeFixtures


class IntakeIncentivePretriggerTests(IntakeFixtures):
    def create_order(self, user=None, **changes):
        self.client.force_login(user or self.clerk)
        response = self.client.post(reverse("order_start"), {
            **self.complete_data(), "id_front": self.image("f.png"), "id_back": self.image("b.png"),
            "_submission_key": str(uuid.uuid4()), **changes})
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        return SalesOrder.objects.get()

    def test_new_store_order_gets_incentive_by_established_date(self):
        campaign = make_campaign(
            name="速克達原廠獎勵", items={"sales_bonus": Decimal("2000")}, vehicle_models=[self.model],
            effective_from=timezone.localdate() - timedelta(days=30), source_types=["store", "dealer", "platform"],
        )
        order = self.create_order()
        self.assertIsNone(order.registration_completed_at)
        self.assertEqual(order.reward_basis_date, order.established_on)
        profile = order.operations
        self.assertEqual(profile.sales_bonus, Decimal("2000"), "建單當下就依訂單成立日帶入實銷獎勵金")
        self.assertEqual(profile.incentive_registration_date, order.established_on)
        self.assertEqual(list(profile.incentive_applications.values_list("campaign_id", flat=True)), [campaign.pk])

    def test_new_dealer_order_gets_dealer_reward_by_established_date(self):
        campaign = DealerRewardCampaign.objects.create(name="機油活動", effective_from=timezone.localdate() - timedelta(days=10))
        campaign.vehicle_models.set([self.model])
        DealerRewardCampaignItem.objects.create(campaign=campaign, reward_type="physical", name="機油", quantity=2, unit="瓶")
        order = self.create_order(user=self.root, source_type="dealer", source=str(self.dealer.pk))
        self.assertEqual(order.source_id, self.dealer.pk)
        self.assertEqual(list(order.dealer_reward_lines.values_list("campaign_id", "quantity")), [(campaign.pk, 2)])

    def test_new_order_without_matching_campaign_stays_zero(self):
        make_campaign(
            name="未來活動", items={"sales_bonus": Decimal("2000")}, vehicle_models=[self.model],
            effective_from=timezone.localdate() + timedelta(days=1), source_types=["store", "dealer", "platform"],
        )
        profile = self.create_order().operations
        self.assertEqual(profile.sales_bonus, Decimal("0"))
        self.assertIsNone(profile.incentive_registration_date)
        self.assertFalse(profile.incentive_applications.exists())
