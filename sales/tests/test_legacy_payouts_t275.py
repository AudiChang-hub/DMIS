"""T-275 第 10 項（使用者 2026-11-21 選 A）：Excel 匯入舊單的車行傭金納入給付頁。

- 給付金額＝Excel 的車行傭金支出＋友善車行獎金支出＋首賣獎金支出＋台數獎金支出（四欄加總，不重算）。
- 領牌日早於 PAYOUT_START_DATE 的匯入車行單：程式判定「匯入前已結清」，不寫給付紀錄、不算未給付。
  使用者可以個別改回未給付（這時才建立一筆給付紀錄）。
- 10-05 以後的匯入車行單：同樣四欄加總，照一般流程判斷已給付與否。
- 系統的台數獎金與車行實物獎勵不因此拉進 10-05 以前；系統建立的舊單也不列。
"""
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from sales.models import (
    DealerRewardCampaign, DealerRewardCampaignItem, DealerVolumeBonusRule, DealerVolumeBonusTier,
    LegacyImportBatch, LegacyImportRow, LegacySalesSnapshot, OrderDealerRewardLine, OrderOperationsProfile,
    OrderVolumeBonus, SalesOrder,
)
from sales.reporting import payouts
from sales.reporting.payout_models import DealerPayoutEntry, DealerPayoutEvent
from sales.services import operations_cockpit
from sales.services.volume_bonus import recompute_rule
from sales.tests.test_dealer_payouts_t150 import KEY, PayoutTestBase

BEFORE = date(2026, 9, 1)
AFTER = date(2026, 10, 20)


class LegacyPayoutBase(PayoutTestBase):
    def setUp(self):
        cache.clear()
        self.batch = LegacyImportBatch.objects.create(import_type="operations", original_filename="synthetic.xlsx", file_size=0)

    def imported(self, day=BEFORE, commission=2000, friendly=3000, first_sale=1000, volume=200, **kwargs):
        order = self.registered(day=day, **kwargs)
        row = LegacyImportRow.objects.create(batch=self.batch, sheet_name="銷貨", source_row=order.pk,
                                             fingerprint=f"t275-payout-{order.pk}")
        LegacySalesSnapshot.objects.create(order=order, import_row=row)
        OrderOperationsProfile.objects.filter(order=order).update(
            dealer_commission_expense=commission, friendly_dealer_bonus_expense=friendly,
            first_sale_bonus_expense=first_sale, volume_bonus_expense=volume)
        return SalesOrder.objects.get(pk=order.pk)


class LegacyPayoutItemTests(LegacyPayoutBase):
    def test_imported_order_before_start_is_prior_settled_with_four_column_total(self):
        order = self.imported()
        item = payouts.current_item(KEY.format(order.pk))
        self.assertIsNotNone(item)
        self.assertEqual(item.amount, Decimal("6200"))
        self.assertEqual(item.status, "prior_settled")
        self.assertEqual(item.status_label, "匯入前已結清")
        self.assertEqual(item.method_label, "匯入前已結清")
        self.assertEqual(item.methods, ())
        self.assertFalse(DealerPayoutEntry.objects.exists())

    def test_prior_settled_is_not_unpaid_and_not_in_method_filters(self):
        order = self.imported()
        items = payouts.collect_items()
        totals = payouts.totals(items)
        self.assertEqual((totals["unpaid_amount"], totals["unpaid_count"]), (Decimal("0"), 0))
        self.assertEqual(totals["paid_amount"], Decimal("0"))
        self.assertEqual((totals["prior_settled_count"], totals["prior_settled_amount"]), (1, Decimal("6200")))
        self.assertEqual(payouts.filter_items(items, status="unpaid"), [])
        self.assertEqual(payouts.filter_items(items, method="separate"), [])
        self.assertEqual([i.order for i in payouts.filter_items(items, status="prior_settled")], [order])
        [group] = payouts.summarize(items)
        self.assertEqual(group["unpaid_amount"], Decimal("0"))
        self.assertTrue(group["orders"][0]["all_paid"])

    def test_cockpit_unpaid_payouts_unchanged(self):
        self.imported()
        self.assertEqual(operations_cockpit._payouts()["unpaid_count"], 0)
        self.assertEqual(operations_cockpit._payouts()["unpaid_amount"], Decimal("0"))

    def test_zero_store_and_system_orders_before_start_stay_out(self):
        zero = self.imported(commission=0, friendly=0, first_sale=0, volume=0)
        store = self.imported(source_type="store", source=self.staff)
        system = self.registered(day=BEFORE)
        keys = self.keys()
        for order in (zero, store, system):
            self.assertNotIn(KEY.format(order.pk), keys)

    def test_imported_order_after_start_uses_same_total_and_normal_flow(self):
        order = self.imported(day=AFTER)
        item = payouts.current_item(KEY.format(order.pk))
        self.assertEqual(item.amount, Decimal("6200"))
        self.assertEqual(item.status, "unpaid")
        self.assertEqual(item.method_label, "另付")
        self.assertEqual(payouts.totals([item])["unpaid_amount"], Decimal("6200"))

    def test_breakdown_lists_nonzero_excel_columns(self):
        order = self.imported(first_sale=0)
        item = payouts.current_item(KEY.format(order.pk))
        self.assertEqual(item.period_label, "Excel：車行傭金 $2,000＋友善車行獎金 $3,000＋台數獎金 $200")


class LegacyPayoutWriteTests(LegacyPayoutBase):
    def test_revert_to_unpaid_creates_entry_then_normal_flow(self):
        order = self.imported()
        key = KEY.format(order.pk)
        self.assertEqual(payouts.set_paid([key], False, "staffb"), 1)
        entry = DealerPayoutEntry.objects.get(source_key=key)
        self.assertFalse(entry.paid)
        self.assertEqual(entry.events.get().action, DealerPayoutEvent.Action.UNPAID)
        item = payouts.current_item(key)
        self.assertEqual(item.status, "unpaid")
        self.assertEqual(item.method_label, "另付")
        self.assertEqual(payouts.totals([item])["unpaid_amount"], Decimal("6200"))
        self.assertEqual(payouts.set_paid([key], True, "staffb"), 1)
        self.assertEqual(payouts.current_item(key).status, "paid")

    def test_marking_prior_settled_paid_writes_nothing(self):
        order = self.imported()
        self.assertEqual(payouts.set_paid([KEY.format(order.pk)], True, "staffb"), 0)
        self.assertFalse(DealerPayoutEntry.objects.exists())

    def test_note_on_prior_settled_is_refused_without_writing(self):
        order = self.imported()
        with self.assertRaises(ValidationError):
            payouts.save_note(KEY.format(order.pk), "補記", "staffb")
        self.assertFalse(DealerPayoutEntry.objects.exists())


class LegacyPayoutScopeTests(LegacyPayoutBase):
    """只放寬傭金：台數獎金、實物獎勵仍只列 10-05 以後。"""

    def test_rewards_before_start_still_not_listed(self):
        order = self.imported()
        campaign = DealerRewardCampaign.objects.create(
            name="九月送機油", brands=["SUZUKI"], effective_from=date(2026, 9, 1), effective_to=date(2026, 9, 30))
        DealerRewardCampaignItem.objects.create(
            campaign=campaign, reward_type="physical", name="機油", unit="罐", quantity=3)
        OrderDealerRewardLine.objects.create(
            order=order, campaign=campaign, campaign_name=campaign.name, dealer=self.dealer,
            reward_type="physical", name="機油", unit="罐", quantity=3, registration_date=BEFORE)
        self.assertEqual([i for i in payouts.collect_items() if i.kind == "reward"], [])

    def test_volume_bonus_period_before_start_still_not_listed(self):
        self.imported(), self.imported(day=date(2026, 9, 10))
        rule = DealerVolumeBonusRule.objects.create(name="九月衝量", starts_on=date(2026, 9, 1), ends_on=date(2026, 9, 30))
        DealerVolumeBonusTier.objects.create(rule=rule, minimum_quantity=1, bonus_per_vehicle=500)
        recompute_rule(rule.pk)
        self.assertTrue(OrderVolumeBonus.objects.exists())
        self.assertEqual([i for i in payouts.collect_items(include_estimate=True) if i.kind == "volume_bonus"], [])


class LegacyPayoutViewTests(LegacyPayoutBase):
    def test_page_shows_prior_settled_without_writing(self):
        order = self.imported()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dealer_payout_list"))
        self.assertContains(response, order.number)
        self.assertContains(response, "匯入前已結清")
        self.assertContains(response, "改回未給付")
        self.assertNotContains(response, "全部標記已給付")
        self.client.get(reverse("dealer_payout_export"))
        self.assertFalse(DealerPayoutEntry.objects.exists())

    def test_post_unpaid_reverts_prior_settled(self):
        order = self.imported()
        self.client.force_login(self.admin)
        self.client.post(reverse("dealer_payout_update"), {"action": "unpaid", "key": KEY.format(order.pk)})
        self.assertFalse(DealerPayoutEntry.objects.get(source_key=KEY.format(order.pk)).paid)
        self.assertEqual(payouts.current_item(KEY.format(order.pk)).status, "unpaid")
