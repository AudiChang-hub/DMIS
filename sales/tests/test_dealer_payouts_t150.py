"""T-150 車行傭金／獎金給付（使用者 2026-11-11 選 A）：應付即時計算，給付紀錄只記勾選、快照、備註與歷程。

來源：傭金、台數獎金（T-148 OrderVolumeBonus）、實物獎勵（T-149 OrderDealerRewardLine）。
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from threading import Barrier
from unittest import skipUnless
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import (
    DealerRewardCampaign, DealerRewardCampaignItem, DealerRewardCatalogItem, DealerVolumeBonusRule, DealerVolumeBonusTier, OrderOperationsProfile, SalesOrder, SalesSource, VehicleBrand,
    VehicleColor, VehicleModel,
)
from sales.reporting.payout_models import DealerPayoutEntry, DealerPayoutEvent
from sales.reporting import payouts
from sales.services.dealer_commission import apply_order_dealer_commission
from sales.services.dealer_reward_campaign import apply_order_dealer_rewards
from sales.services.dealer_settlement import dealer_settlement
from sales.services.volume_bonus import recompute_rule
from sales.tests import test_finance_ledger as ledger

KEY = "commission:order:{}"


class PayoutTestBase(ledger.FinanceLedgerTestBase):
    def registered(self, day=date(2026, 10, 20), **kwargs):
        order = self.make_order(**kwargs)
        SalesOrder.all_objects.filter(pk=order.pk).update(
            registration_date=day, registration_completed_at=timezone.now(), status="completed")
        return SalesOrder.objects.get(pk=order.pk)

    def keys(self, **kwargs):
        return [item.source_key for item in payouts.collect_items(**kwargs)]


class PayoutItemTests(PayoutTestBase):
    def test_commission_listed_after_registration_from_start_date(self):
        listed = self.registered()
        early = self.registered(day=date(2026, 10, 4))
        pending = self.make_order()
        keys = self.keys()
        self.assertIn(KEY.format(listed.pk), keys)
        self.assertNotIn(KEY.format(early.pk), keys)
        self.assertNotIn(KEY.format(pending.pk), keys)
        item = payouts.current_item(KEY.format(listed.pk))
        self.assertEqual(item.amount, Decimal("2300"))
        self.assertEqual(item.dealer, self.dealer)
        self.assertEqual(item.label, "結算車型 白 傭金")

    def test_store_cancelled_returned_and_zero_commission_are_not_listed(self):
        store = self.registered(source_type="store", source=self.staff)
        cancelled = self.registered()
        SalesOrder.all_objects.filter(pk=cancelled.pk).update(status="cancelled")
        closed = self.registered()
        SalesOrder.all_objects.filter(pk=closed.pk).update(status="exception_closed")
        zero = self.registered()
        OrderOperationsProfile.objects.filter(order=zero).update(
            dealer_commission_expense=0, manual_financial_fields=["dealer_commission_expense"])
        keys = self.keys()
        for order in (store, cancelled, closed, zero):
            self.assertNotIn(KEY.format(order.pk), keys)

    def test_commission_goes_to_attributed_dealer(self):
        order = self.registered()
        SalesOrder.all_objects.filter(pk=order.pk).update(commission_recipient=self.other_dealer)
        self.assertEqual(payouts.current_item(KEY.format(order.pk)).dealer, self.other_dealer)

    def test_deduction_only_for_system_cash_dealer_orders(self):
        cash = self.registered(cash_receivable_v2=True)
        installment = self.registered(
            cash_receivable_v2=True, payment_type="installment", installment_amount=Decimal("60000"),
            installment_company="測試分期", installment_periods=24,
            payment_splits=[{"method": "cash", "amount": 19800}, {"method": "installment", "amount": 60000}])
        self.assertTrue(payouts.current_item(KEY.format(cash.pk)).deduction)
        self.assertFalse(payouts.current_item(KEY.format(installment.pk)).deduction)
        self.assertEqual(payouts.current_item(KEY.format(installment.pk)).method_label, "另付")


class PayoutWriteTests(PayoutTestBase):
    def test_mark_unmark_and_history(self):
        order = self.registered()
        key = KEY.format(order.pk)
        self.assertEqual(payouts.set_paid([key], True, "nina"), 1)
        entry = DealerPayoutEntry.objects.get(source_key=key)
        self.assertEqual((entry.paid, entry.paid_amount, entry.paid_by, entry.dealer, entry.order),
                         (True, Decimal("2300"), "nina", self.dealer, order))
        self.assertEqual(payouts.set_paid([key], True, "nina"), 0)
        self.assertEqual(payouts.set_paid([key], False, "morris"), 1)
        entry.refresh_from_db()
        self.assertFalse(entry.paid)
        self.assertEqual(list(entry.events.order_by("pk").values_list("action", "actor_name")),
                         [("paid", "nina"), ("unpaid", "morris")])

    def test_unmarking_untouched_item_creates_nothing(self):
        order = self.registered()
        self.assertEqual(payouts.set_paid([KEY.format(order.pk)], False, "nina"), 0)
        self.assertFalse(DealerPayoutEntry.objects.exists())

    def test_batch_is_all_or_nothing(self):
        order = self.registered()
        with self.assertRaises(ValidationError):
            payouts.set_paid([KEY.format(order.pk), "commission:order:999999"], True, "nina")
        self.assertFalse(DealerPayoutEntry.objects.exists())

    def test_amount_change_after_payment_is_flagged_then_confirmed(self):
        order = self.registered()
        key = KEY.format(order.pk)
        payouts.set_paid([key], True, "nina")
        OrderOperationsProfile.objects.filter(order=order).update(dealer_commission_expense=2800)
        item = payouts.current_item(key)
        self.assertTrue(item.paid)
        self.assertEqual((item.status, item.difference), ("changed", Decimal("500")))
        payouts.confirm_difference(key, "morris")
        item = payouts.current_item(key)
        self.assertEqual(item.status, "paid")
        self.assertEqual(item.entry.paid_amount, Decimal("2800"))
        self.assertTrue(DealerPayoutEvent.objects.filter(entry=item.entry, action="confirm_difference").exists())
        with self.assertRaises(ValidationError):
            payouts.confirm_difference(key, "morris")

    def test_note_saved_with_history_even_before_payment(self):
        order = self.registered()
        key = KEY.format(order.pk)
        self.assertFalse(payouts.save_note(key, "  ", "nina"))
        self.assertFalse(DealerPayoutEntry.objects.exists())
        self.assertTrue(payouts.save_note(key, "11/20 匯款", "nina"))
        self.assertFalse(payouts.save_note(key, "11/20 匯款", "nina"))
        self.assertEqual(payouts.current_item(key).note, "11/20 匯款")
        event = DealerPayoutEvent.objects.get(action="note")
        self.assertEqual((event.note_before, event.note_after), ("", "11/20 匯款"))
        with self.assertRaises(ValidationError):
            payouts.save_note(key, "長" * 501, "nina")

    def test_paid_item_whose_source_disappears_is_an_orphan_until_resolved(self):
        order = self.registered()
        key = KEY.format(order.pk)
        payouts.set_paid([key], True, "nina")
        SalesOrder.all_objects.filter(pk=order.pk).update(status="exception_closed")
        items = payouts.collect_items()
        orphans = payouts.orphan_entries(items)
        self.assertEqual([entry.source_key for entry in orphans], [key])
        with self.assertRaises(ValidationError):
            payouts.set_paid([key], False, "nina")
        payouts.resolve_orphan(orphans[0].pk, "morris")
        self.assertEqual(payouts.orphan_entries(payouts.collect_items()), [])

    def test_payment_does_not_touch_settlement_or_profit_fields(self):
        order = self.registered(cash_receivable_v2=True)
        profile_before = OrderOperationsProfile.objects.filter(order=order).values().get()
        settlement_before = dealer_settlement(order)
        payouts.set_paid([KEY.format(order.pk)], True, "nina")
        payouts.save_note(KEY.format(order.pk), "已抵扣", "nina")
        order = SalesOrder.objects.get(pk=order.pk)
        self.assertEqual(OrderOperationsProfile.objects.filter(order=order).values().get(), profile_before)
        self.assertEqual(dealer_settlement(order), settlement_before)


class PayoutSummaryTests(PayoutTestBase):
    def test_dealer_totals_split_paid_and_unpaid(self):
        first, second = self.registered(), self.registered(day=date(2026, 11, 2))
        payouts.set_paid([KEY.format(first.pk)], True, "nina")
        items = payouts.collect_items()
        group = payouts.summarize(items)[0]
        self.assertEqual((group["unpaid_amount"], group["paid_amount"]), (Decimal("2300"), Decimal("2300")))
        self.assertEqual([row["order"].pk for row in group["orders"]], [first.pk, second.pk])
        totals = payouts.totals(items)
        self.assertEqual((totals["unpaid_count"], totals["dealer_count"]), (1, 1))
        filtered = payouts.filter_items(items, status="unpaid", start=date(2026, 11, 1))
        self.assertEqual([item.order.pk for item in filtered], [second.pk])


class PayoutViewTests(PayoutTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.viewer = get_user_model().objects.create_user("viewer", password="Test-Only-123")
        UserAccessState.objects.create(user=cls.viewer, configured=True)
        ScreenAccessGrant.objects.create(user=cls.viewer, screen_key="dealer_payouts", view=True)
        cls.nobody = get_user_model().objects.create_user("nobody", password="Test-Only-123")
        UserAccessState.objects.create(user=cls.nobody, configured=True)

    def test_page_lists_rows_and_report_center_lands_on_it(self):
        order = self.registered()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dealer_payout_list"))
        self.assertContains(response, "車行傭金／獎金給付")
        self.assertContains(response, order.number)
        self.assertContains(response, "結算車行")
        self.assertContains(response, "$2,300")
        self.assertRedirects(self.client.get(reverse("report_center")), reverse("dealer_payout_list"))

    def test_get_does_not_write(self):
        self.registered()
        self.client.force_login(self.admin)
        self.client.get(reverse("dealer_payout_list"), {"status": "unpaid", "estimate": "1"})
        self.client.get(reverse("dealer_payout_export"))
        self.assertFalse(DealerPayoutEntry.objects.exists())

    def test_post_marks_paid_and_returns_to_same_filters(self):
        order = self.registered()
        self.client.force_login(self.admin)
        back = reverse("dealer_payout_list") + "?status=unpaid"
        response = self.client.post(reverse("dealer_payout_update"),
                                    {"action": "paid", "key": KEY.format(order.pk), "next": back})
        self.assertRedirects(response, back)
        self.assertTrue(DealerPayoutEntry.objects.get().paid)
        response = self.client.post(reverse("dealer_payout_update"),
                                    {"action": "paid", "key": KEY.format(order.pk), "next": "https://evil.example/"})
        self.assertRedirects(response, reverse("dealer_payout_list"))

    def test_view_only_cannot_write_and_no_grant_is_denied(self):
        order = self.registered()
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("dealer_payout_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("report_center")).status_code, 302)
        self.assertEqual(self.client.post(reverse("dealer_payout_update"),
                                          {"action": "paid", "key": KEY.format(order.pk)}).status_code, 403)
        self.assertEqual(self.client.get(reverse("dealer_payout_export")).status_code, 403)
        self.assertFalse(DealerPayoutEntry.objects.exists())
        self.client.force_login(self.nobody)
        self.assertEqual(self.client.get(reverse("dealer_payout_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("report_center")).status_code, 403)

    def test_csv_export_is_formula_safe(self):
        order = self.registered()
        payouts.save_note(KEY.format(order.pk), "=HYPERLINK(\"x\")", "nina")
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dealer_payout_export"))
        text = response.content.decode("utf-8-sig")
        self.assertIn("結算車行,傭金,", text)
        self.assertIn("'=HYPERLINK", text)

    def test_legacy_unconfigured_account_needs_explicit_grant(self):
        legacy = get_user_model().objects.create_user("legacy-payout", password="Test-Only-123")
        self.client.force_login(legacy)
        self.assertEqual(self.client.get(reverse("dealer_payout_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("dealer_payout_export")).status_code, 403)
        self.assertEqual(self.client.post(reverse("dealer_payout_update"), {"action": "paid"}).status_code, 403)


class PayoutVolumeBonusTests(TestCase):
    """台數獎金（T-148 OrderVolumeBonus）：每期 × 每家車行 × 每條規則一列；期間結束入帳才可勾選。"""
    OCT = (date(2026, 10, 1), date(2026, 10, 31))
    DURING = timezone.make_aware(datetime(2026, 10, 20, 10))
    AFTER = timezone.make_aware(datetime(2026, 11, 1, 4))

    @classmethod
    def setUpTestData(cls):
        cls.dealer = SalesSource.objects.create(name="旭昶", source_type="dealer")
        VehicleBrand.objects.get_or_create(name="SUZUKI")
        cls.model = VehicleModel.objects.create(brand="SUZUKI", name="SUI", energy_type="gas", base_dealer_commission=2000)
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="黃色")

    def order(self, day=date(2026, 10, 8)):
        order = SalesOrder.objects.create(
            source=self.dealer, source_type="dealer", order_date=day, owner_type="company", owner_name="測試公司",
            owner_id_number="83739807", owner_phone="0912345678", owner_address="測試地址", vehicle_model=self.model,
            color=self.color, vehicle_price=70000, actual_balance=70000, calculated_balance=70000, payment_type="cash",
            registration_date=day, registration_completed_at=timezone.now(), status="delivery_pending")
        apply_order_dealer_commission(order, lock=True)
        return order

    def rule(self):
        rule = DealerVolumeBonusRule.objects.create(name="十月衝量", starts_on=self.OCT[0], ends_on=self.OCT[1])
        DealerVolumeBonusTier.objects.create(rule=rule, minimum_quantity=2, bonus_per_vehicle=500)
        return rule

    def bonus_items(self, **kwargs):
        return [item for item in payouts.collect_items(**kwargs) if item.kind == "volume_bonus"]

    def test_estimate_only_listed_on_request_and_not_checkable(self):
        self.order(), self.order(date(2026, 10, 20))
        rule = self.rule()
        recompute_rule(rule.pk, now=self.DURING)
        self.assertEqual(self.bonus_items(), [])
        [item] = self.bonus_items(include_estimate=True)
        self.assertTrue(item.estimate)
        self.assertFalse(item.checkable)
        self.assertEqual(item.status, "estimate")
        with self.assertRaises(ValidationError):
            payouts.set_paid([item.source_key], True, "nina")

    def test_posted_bonus_is_one_row_per_period_and_commission_excludes_it(self):
        first, second = self.order(), self.order(date(2026, 10, 20))
        rule = self.rule()
        recompute_rule(rule.pk, now=self.AFTER)
        [item] = self.bonus_items()
        self.assertEqual((item.amount, item.dealer, item.short_label), (Decimal("1000"), self.dealer, "十月衝量"))
        self.assertIn("2 台，達 2 台門檻", item.period_label)
        self.assertEqual([detail["number"] for detail in item.details], [first.number, second.number])
        self.assertEqual(item.method_label, "另付")
        self.assertEqual(OrderOperationsProfile.objects.get(order=first).dealer_commission_expense, Decimal("2500"))
        commission = payouts.current_item(f"commission:order:{first.pk}")
        self.assertEqual(commission.amount, Decimal("2000"))
        self.assertEqual(payouts.totals(payouts.collect_items())["unpaid_amount"], Decimal("5000"))

    def test_paid_bonus_recalculated_is_flagged_and_vanished_bonus_is_orphan(self):
        first, second = self.order(), self.order(date(2026, 10, 20))
        rule = self.rule()
        recompute_rule(rule.pk, now=self.AFTER)
        [item] = self.bonus_items()
        payouts.set_paid([item.source_key], True, "nina")
        self.order(date(2026, 10, 25))
        recompute_rule(rule.pk, now=self.AFTER)
        [item] = self.bonus_items()
        self.assertEqual((item.status, item.difference), ("changed", Decimal("500")))
        for order in (first, second):
            SalesOrder.all_objects.filter(pk=order.pk).update(status="cancelled")
        recompute_rule(rule.pk, now=self.AFTER)
        self.assertEqual(self.bonus_items(), [])
        self.assertEqual([entry.source_key for entry in payouts.orphan_entries(payouts.collect_items())], [item.source_key])


class PayoutRewardTests(PayoutTestBase):
    """車行實物獎勵（T-149 OrderDealerRewardLine）：每張單 × 活動 × 品項一列，記數量不記金額。"""

    def setUp(self):
        self.oil = DealerRewardCatalogItem.objects.create(reward_type="physical", name="機油", unit="罐")
        self.campaign = DealerRewardCampaign.objects.create(
            name="十月送機油", brands=["SUZUKI"], effective_from=date(2026, 10, 1), effective_to=date(2026, 10, 31))
        self.oil_item = DealerRewardCampaignItem.objects.create(
            campaign=self.campaign, catalog_item=self.oil, reward_type="physical", name="機油", unit="罐", quantity=3)
        DealerRewardCampaignItem.objects.create(
            campaign=self.campaign, reward_type="voucher", name="禮券", unit="元", quantity=500)

    def rewarded(self, **kwargs):
        order = self.registered(**kwargs)
        apply_order_dealer_rewards(order, force=True)
        return order

    def reward_items(self):
        return [item for item in payouts.collect_items() if item.kind == "reward"]

    def test_each_campaign_item_is_a_quantity_row_beside_commission(self):
        order = self.rewarded()
        oil, voucher = self.reward_items()
        self.assertEqual((oil.short_label, oil.quantity, oil.unit, oil.dealer), ("機油", Decimal("3"), "罐", self.dealer))
        self.assertEqual(oil.period_label, "十月送機油")
        self.assertTrue(oil.source_key.startswith(f"reward:order:{order.pk}:campaign:{self.campaign.pk}:catalog:"))
        self.assertTrue(voucher.source_key.startswith(f"reward:order:{order.pk}:campaign:{self.campaign.pk}:name:"))
        group = payouts.summarize(payouts.collect_items())[0]
        self.assertEqual([item.kind for item in group["orders"][0]["items"]], ["commission", "reward", "reward"])
        self.assertEqual(group["unpaid_amount"], Decimal("2300"))  # 實物不算進金額
        self.assertEqual([(goods["label"], goods["quantity"]) for goods in group["unpaid_goods"]],
                         [("機油", "3"), ("禮券", "500")])

    def test_paid_quantity_survives_reapply_and_flags_change(self):
        order = self.rewarded()
        oil = self.reward_items()[0]
        payouts.set_paid([oil.source_key], True, "nina")
        entry = DealerPayoutEntry.objects.get(source_key=oil.source_key)
        self.assertEqual((entry.paid_quantity, entry.paid_unit, entry.paid_amount), (Decimal("3"), "罐", None))
        self.oil_item.quantity = 5
        self.oil_item.save()
        apply_order_dealer_rewards(SalesOrder.objects.get(pk=order.pk), force=True)  # 明細刪掉重建，代碼不變
        oil = self.reward_items()[0]
        self.assertEqual((oil.status, oil.paid), ("changed", True))
        payouts.confirm_difference(oil.source_key, "nina")
        self.assertEqual(DealerPayoutEntry.objects.get(source_key=oil.source_key).paid_quantity, Decimal("5"))

    def test_store_order_assigned_to_dealer_lists_reward_but_not_commission(self):
        order = self.rewarded(source_type="store", source=self.staff, commission_recipient=self.dealer)
        keys = [item.source_key for item in payouts.collect_items()]
        self.assertNotIn(KEY.format(order.pk), keys)
        self.assertEqual({item.dealer for item in self.reward_items()}, {self.dealer})

    def test_page_shows_goods_summary(self):
        self.rewarded()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dealer_payout_list"))
        self.assertContains(response, "機油 × 3罐")
        self.assertContains(response, "十月送機油")


@skipUnless(connection.vendor == "postgresql", "需 PostgreSQL 驗證列鎖")
class PayoutConcurrencyTests(TransactionTestCase):
    """兩人同時勾同一列：只會有一筆給付紀錄、一筆「標記已給付」歷程（select_for_update of self＋唯一鍵）。"""

    def test_two_people_marking_same_item_create_one_entry(self):
        dealer = SalesSource.objects.create(name="併發車行", source_type="dealer")
        model = VehicleModel.objects.create(brand="SUZUKI", name="併發車", energy_type="gas", base_dealer_commission=2000)
        color = VehicleColor.objects.create(vehicle_model=model, name="白")
        order = SalesOrder.objects.create(
            source=dealer, source_type="dealer", order_date=date(2026, 10, 8), owner_type="company", owner_name="測試公司",
            owner_id_number="83739807", owner_phone="0912345678", owner_address="測試地址", vehicle_model=model,
            color=color, vehicle_price=70000, actual_balance=70000, calculated_balance=70000, payment_type="cash",
            registration_date=date(2026, 10, 8), registration_completed_at=timezone.now(), status="completed")
        apply_order_dealer_commission(order, lock=True)
        key = KEY.format(order.pk)
        barrier = Barrier(2)

        def mark(actor):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return payouts.set_paid([key], True, actor)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(mark, actor) for actor in ("nina", "morris")]
            self.assertCountEqual([future.result(timeout=30) for future in futures], [1, 0])
        self.assertEqual(DealerPayoutEntry.objects.filter(source_key=key).count(), 1)
        self.assertEqual(DealerPayoutEvent.objects.filter(entry__source_key=key, action="paid").count(), 1)
