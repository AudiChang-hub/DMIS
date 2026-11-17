"""T-203：台數獎金月底手動結算後才生效（使用者 2026-11-17 選 C，取代 T-148「期間結束自動入帳」）。

- 期間內和期間結束後都只是試算：不進傭金支出、淨利、車行結算卡、掛帳。
- 在報表中心〈車行傭金／獎金給付〉的台數獎金列按「結算」（規則×期間×車行一組），才加進各單傭金支出。
- 結算後顯示「待發放」，付給車行後勾「已給付」；不扣任何應收或掛帳。
- 結算後金額固定，有變動只標「結算後有變」；可取消後重新結算，已給付的要先取消給付。
"""
import importlib
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import (
    DealerVolumeBonusRule,
    DealerVolumeBonusTier,
    OrderEvent,
    OrderOperationsProfile,
    OrderVolumeBonus,
    SalesOrder,
    SalesSource,
    VehicleBrand,
    VehicleColor,
    VehicleModel,
    VolumeBonusSettlement,
)
from sales.reporting import payouts
from sales.reporting.payout_models import DealerPayoutEntry
from sales.services.bonus_rule_deletion import bonus_rule_delete_preview
from sales.services.customer_receivable import dealer_account_due
from sales.services.dealer_commission import apply_order_dealer_commission
from sales.services.dealer_settlement import dealer_settlement
from sales.services.order_workspace import unsettled_volume_bonus
from sales.services.volume_bonus import (
    cancel_settlement,
    recompute_rule,
    settle_group,
    settlement_changes,
    sync_all,
)

OCT = (date(2026, 10, 1), date(2026, 10, 31))
AFTER = timezone.make_aware(datetime(2026, 11, 1, 9))


def make_dealer_order(dealer, model, color, day=date(2026, 10, 8), **overrides):
    values = dict(
        source=dealer, source_type="dealer", order_date=day, owner_type="company", owner_name="測試公司",
        owner_id_number="83739807", owner_phone="0912345678", owner_address="測試地址", vehicle_model=model,
        color=color, vehicle_price=70000, actual_balance=70000, calculated_balance=70000, payment_type="cash",
        registration_date=day, registration_completed_at=timezone.now(), status="delivery_pending")
    values.update(overrides)
    order = SalesOrder.objects.create(**values)
    apply_order_dealer_commission(order, lock=True)
    return order


class SettleTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dealer = SalesSource.objects.create(name="結算車行", source_type="dealer")
        cls.other = SalesSource.objects.create(name="另一車行", source_type="dealer")
        VehicleBrand.objects.get_or_create(name="SUZUKI")
        cls.model = VehicleModel.objects.create(brand="SUZUKI", name="結算車", energy_type="gas", base_dealer_commission=2000)
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="白")

    def order(self, day=date(2026, 10, 8), **overrides):
        return make_dealer_order(self.dealer, self.model, self.color, day, **overrides)

    def rule(self, minimum=2, amount=500):
        rule = DealerVolumeBonusRule.objects.create(name="十月衝量", starts_on=OCT[0], ends_on=OCT[1])
        DealerVolumeBonusTier.objects.create(rule=rule, minimum_quantity=minimum, bonus_per_vehicle=amount)
        return rule

    def scope(self, rule):
        return rule.pk, rule.periods.get().pk, self.dealer.pk

    def expense(self, order):
        return OrderOperationsProfile.objects.get(order=order).dealer_commission_expense

    def bonus_items(self, **kwargs):
        return [item for item in payouts.collect_items(**kwargs) if item.kind == "volume_bonus"]


class SettleServiceTests(SettleTestBase):
    def test_ended_period_stays_trial_until_settled(self):
        first, second = self.order(), self.order(date(2026, 10, 20))
        rule = self.rule()
        recompute_rule(rule.pk, now=AFTER)
        sync_all(now=AFTER)
        self.assertEqual(OrderVolumeBonus.objects.filter(rule=rule, posted_at__isnull=True).count(), 2)
        self.assertEqual((self.expense(first), self.expense(second)), (2000, 2000))
        self.assertEqual(unsettled_volume_bonus(first), 500)

        settlement = settle_group(*self.scope(rule), "〔人員〕", expected_total=1000, now=AFTER)
        self.assertEqual((settlement.quantity, settlement.total_amount, settlement.settled_by), (2, 1000, "〔人員〕"))
        self.assertEqual((self.expense(first), self.expense(second)), (2500, 2500))
        self.assertEqual(unsettled_volume_bonus(first), 0)
        self.assertEqual(OrderVolumeBonus.objects.filter(rule=rule, posted_at=AFTER).count(), 2)
        event = OrderEvent.objects.get(order=first, event_type="volume_bonus_settled")
        self.assertIn("加進傭金支出", event.description)
        self.assertEqual(sync_all(now=AFTER), 0)
        self.assertEqual(self.expense(first), 2500)

    def test_cannot_settle_before_period_ends_twice_or_with_stale_total(self):
        self.order(), self.order(date(2026, 10, 20))
        rule = self.rule()
        recompute_rule(rule.pk, now=AFTER)
        with self.assertRaisesMessage(ValidationError, "還沒結束"):
            settle_group(*self.scope(rule), "〔人員〕", now=timezone.make_aware(datetime(2026, 10, 31, 22)))
        with self.assertRaisesMessage(ValidationError, "已變動"):
            settle_group(*self.scope(rule), "〔人員〕", expected_total=500, now=AFTER)
        settle_group(*self.scope(rule), "〔人員〕", expected_total=1000, now=AFTER)
        with self.assertRaisesMessage(ValidationError, "已經結算"):
            settle_group(*self.scope(rule), "〔人員〕", now=AFTER)

    def test_group_below_threshold_has_nothing_to_settle(self):
        self.order()
        rule = self.rule()
        recompute_rule(rule.pk, now=AFTER)
        with self.assertRaisesMessage(ValidationError, "沒有達到門檻"):
            settle_group(*self.scope(rule), "〔人員〕", now=AFTER)
        self.assertFalse(VolumeBonusSettlement.objects.exists())

    def test_settled_amount_is_fixed_and_changes_are_flagged(self):
        first, second = self.order(), self.order(date(2026, 10, 20))
        rule = self.rule()
        recompute_rule(rule.pk, now=AFTER)
        settlement = settle_group(*self.scope(rule), "〔人員〕", now=AFTER)
        with self.captureOnCommitCallbacks(execute=True):
            second.registration_date = date(2026, 11, 2)  # 改領牌日移出期間：不自動收回
            second.save()
        self.assertEqual((self.expense(first), self.expense(second)), (2500, 2500))
        self.assertEqual(OrderVolumeBonus.objects.filter(rule=rule, posted_at__isnull=False).count(), 2)
        changes = settlement_changes(settlement)
        self.assertIn("目前 1 台", changes[0])
        self.assertIn(second.number, changes[1])
        with self.captureOnCommitCallbacks(execute=True):
            SalesOrder.all_objects.filter(pk=first.pk).update(status="cancelled")
        self.assertEqual(self.expense(first), 2500)  # 刪單、退車不自動收回

    def test_cancel_settlement_removes_bonus_and_can_settle_again(self):
        first, _second = self.order(), self.order(date(2026, 10, 20))
        rule = self.rule()
        recompute_rule(rule.pk, now=AFTER)
        settle_group(*self.scope(rule), "〔人員〕", now=AFTER)
        third = self.order(date(2026, 10, 25))
        recompute_rule(rule.pk, now=AFTER)
        self.assertFalse(OrderVolumeBonus.objects.filter(order=third).exists())  # 已結算的組不加新單
        cancel_settlement(*self.scope(rule), "〔人員〕", now=AFTER)
        self.assertEqual(self.expense(first), 2000)
        self.assertEqual(OrderVolumeBonus.objects.filter(rule=rule, posted_at__isnull=True).count(), 3)
        old = VolumeBonusSettlement.objects.get()
        self.assertEqual(old.cancelled_by, "〔人員〕")
        self.assertTrue(OrderEvent.objects.filter(order=first, event_type="volume_bonus_settled",
                                                  description__startswith="取消台數獎金結算").exists())
        again = settle_group(*self.scope(rule), "〔人員〕", expected_total=1500, now=AFTER)
        self.assertEqual((again.quantity, again.total_amount), (3, 1500))
        self.assertEqual(VolumeBonusSettlement.objects.count(), 2)
        self.assertEqual(self.expense(third), 2500)

    def test_paid_bonus_must_be_unpaid_before_cancelling(self):
        self.order(), self.order(date(2026, 10, 20))
        rule = self.rule()
        recompute_rule(rule.pk, now=AFTER)
        settle_group(*self.scope(rule), "〔人員〕", now=AFTER)
        [item] = self.bonus_items()
        payouts.set_paid([item.source_key], True, "〔人員〕")
        with self.assertRaisesMessage(ValidationError, "先取消已給付"):
            cancel_settlement(*self.scope(rule), "〔人員〕", now=AFTER)
        payouts.set_paid([item.source_key], False, "〔人員〕")
        cancel_settlement(*self.scope(rule), "〔人員〕", now=AFTER)

    def test_settlement_card_and_dealer_account_do_not_deduct_bonus(self):
        order, _second = self.order(cash_receivable_v2=True), self.order(date(2026, 10, 20), cash_receivable_v2=True)
        before = dealer_account_due(order)
        rule = self.rule()
        recompute_rule(rule.pk, now=AFTER)
        settle_group(*self.scope(rule), "〔人員〕", now=AFTER)
        order = SalesOrder.objects.get(pk=order.pk)
        card = dealer_settlement(order)
        self.assertEqual(card["volume_bonus"], 500)
        commission = next(term for term in card["terms"] if term["key"] == "commission")
        self.assertEqual(commission["amount"], 2000)  # 傭金支出 2,500 含獎金，卡片只扣其餘 2,000
        self.assertEqual(card["total"], before)  # T-202 第 1 節：卡片與掛帳一致，差額 0
        self.assertEqual(dealer_account_due(order), before)

    def test_rule_with_active_settlement_cannot_be_deleted(self):
        self.order(), self.order(date(2026, 10, 20))
        rule = self.rule()
        recompute_rule(rule.pk, now=AFTER)
        settle_group(*self.scope(rule), "〔人員〕", now=AFTER)
        user = get_user_model().objects.create_superuser("bonus-admin", password="Test-Only-123")
        self.assertEqual(bonus_rule_delete_preview(rule, user)["settlement_count"], 1)
        cancel_settlement(*self.scope(rule), "〔人員〕", now=AFTER)
        self.assertEqual(bonus_rule_delete_preview(rule, user)["settlement_count"], 0)

    def test_order_settled_with_one_dealer_does_not_move_to_another(self):
        first, second = self.order(), self.order(date(2026, 10, 20))
        rule = self.rule(minimum=1)
        recompute_rule(rule.pk, now=AFTER)
        settle_group(*self.scope(rule), "〔人員〕", now=AFTER)
        with self.captureOnCommitCallbacks(execute=True):
            SalesOrder.objects.filter(pk=second.pk).update(commission_recipient=self.other)
            recompute_rule(rule.pk, now=AFTER)
        row = OrderVolumeBonus.objects.get(rule=rule, order=second)
        self.assertEqual((row.dealer, bool(row.posted_at)), (self.dealer, True))
        self.assertFalse(OrderVolumeBonus.objects.filter(rule=rule, dealer=self.other).exists())
        self.assertEqual(self.expense(first), 2500)

    def test_migration_keeps_auto_posted_groups_as_settled(self):
        first, second = self.order(), self.order(date(2026, 10, 20))
        rule = self.rule()
        recompute_rule(rule.pk, now=AFTER)
        OrderVolumeBonus.objects.filter(rule=rule).update(posted_at=AFTER)  # T-148 自動入帳留下的列
        migration = importlib.import_module("sales.migrations.0212_volume_bonus_settlement")
        migration.convert_posted_bonus(apps, None)
        settlement = VolumeBonusSettlement.objects.get()
        self.assertEqual((settlement.quantity, settlement.total_amount, settlement.settled_at),
                         (2, Decimal("1000"), AFTER))
        self.assertEqual(settlement.settled_by, "系統（T-148 自動入帳轉結算）")
        recompute_rule(rule.pk, now=AFTER)
        self.assertEqual(OrderVolumeBonus.objects.filter(rule=rule, posted_at=AFTER).count(), 2)


class SettlePayoutPageTests(SettleTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = get_user_model().objects.create_superuser("admin", password="Test-Only-123")
        cls.viewer = get_user_model().objects.create_user("payout-viewer", password="Test-Only-123")
        UserAccessState.objects.create(user=cls.viewer, configured=True)
        ScreenAccessGrant.objects.create(user=cls.viewer, screen_key="dealer_payouts", view=True)

    def test_estimate_pending_and_settled_states(self):
        self.order(), self.order(date(2026, 10, 20))
        rule = self.rule()
        recompute_rule(rule.pk, now=AFTER)
        with patch("sales.services.volume_bonus.timezone.localdate", return_value=date(2026, 10, 20)):
            self.assertEqual(self.bonus_items(), [])
            [estimate] = self.bonus_items(include_estimate=True)
            self.assertEqual((estimate.status, estimate.checkable), ("estimate", False))

        [pending] = self.bonus_items()  # 期間結束：不用勾「含預估」就列出
        self.assertEqual((pending.status, pending.status_label, pending.checkable), ("settle", "待結算", False))
        totals = payouts.totals(payouts.collect_items())
        self.assertEqual((totals["unpaid_amount"], totals["settle_amount"], totals["settle_count"]),
                         (Decimal("4000"), Decimal("1000"), 1))
        with self.assertRaisesMessage(ValidationError, "請先按「結算」"):
            payouts.set_paid([pending.source_key], True, "〔人員〕")
        self.assertEqual([item.source_key for item in payouts.filter_items(payouts.collect_items(), status="settle")],
                         [pending.source_key])

        settle_group(*self.scope(rule), "〔人員〕", now=AFTER)
        [settled] = self.bonus_items()
        self.assertEqual((settled.status, settled.status_label, settled.checkable, settled.method_label),
                         ("unpaid", "待發放", True, "另付"))
        self.assertEqual(payouts.totals(payouts.collect_items())["unpaid_amount"], Decimal("5000"))
        first_commission = next(item for item in payouts.collect_items() if item.kind == "commission")
        self.assertEqual(first_commission.amount, Decimal("2000"))  # 傭金列不含台數獎金

    def test_settle_and_cancel_from_payout_page(self):
        self.order(), self.order(date(2026, 10, 20))
        rule = self.rule()
        recompute_rule(rule.pk, now=AFTER)
        rule_id, period_id, dealer_id = self.scope(rule)
        self.client.force_login(self.admin)
        page = self.client.get(reverse("dealer_payout_list"))
        self.assertContains(page, "台數獎金待結算 1 組")
        self.assertContains(page, "data-settle-open")
        self.assertContains(page, "確認結算 $1,000")
        back = reverse("dealer_payout_list") + f"?dealer={dealer_id}"
        payload = {"action": "settle", "rule": rule_id, "period": period_id, "dealer": dealer_id,
                   "total": "1000", "next": back}
        self.assertRedirects(self.client.post(reverse("dealer_payout_update"), payload), back)
        self.assertTrue(VolumeBonusSettlement.objects.filter(cancelled_at__isnull=True).exists())
        page = self.client.get(back)
        self.assertContains(page, "待發放")
        self.assertContains(page, "取消結算")
        self.assertNotContains(page, "data-settle-open")
        self.client.post(reverse("dealer_payout_update"), {**payload, "action": "cancel_settlement"})
        self.assertFalse(VolumeBonusSettlement.objects.filter(cancelled_at__isnull=True).exists())

    def test_settlement_needs_operate_permission(self):
        self.order(), self.order(date(2026, 10, 20))
        rule = self.rule()
        recompute_rule(rule.pk, now=AFTER)
        rule_id, period_id, dealer_id = self.scope(rule)
        self.client.force_login(self.viewer)
        page = self.client.get(reverse("dealer_payout_list"))
        self.assertContains(page, "待結算")
        self.assertNotContains(page, "data-settle-open")
        response = self.client.post(reverse("dealer_payout_update"), {
            "action": "settle", "rule": rule_id, "period": period_id, "dealer": dealer_id})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(VolumeBonusSettlement.objects.exists())

    def test_stale_total_shows_error_and_writes_nothing(self):
        self.order(), self.order(date(2026, 10, 20))
        rule = self.rule()
        recompute_rule(rule.pk, now=AFTER)
        rule_id, period_id, dealer_id = self.scope(rule)
        self.client.force_login(self.admin)
        response = self.client.post(reverse("dealer_payout_update"), {
            "action": "settle", "rule": rule_id, "period": period_id, "dealer": dealer_id, "total": "1500"}, follow=True)
        self.assertContains(response, "台數獎金已變動")
        self.assertFalse(VolumeBonusSettlement.objects.exists())


@skipUnless(connection.vendor == "postgresql", "需 PostgreSQL 驗證列鎖")
class SettleConcurrencyTests(TransactionTestCase):
    """兩人同時按同一組結算：只會有一筆有效結算，傭金只加一次（select_for_update of self＋部分唯一索引）。"""

    def test_two_people_settling_same_group_create_one_settlement(self):
        dealer = SalesSource.objects.create(name="併發結算車行", source_type="dealer")
        VehicleBrand.objects.get_or_create(name="SUZUKI")
        model = VehicleModel.objects.create(brand="SUZUKI", name="併發結算車", energy_type="gas", base_dealer_commission=2000)
        color = VehicleColor.objects.create(vehicle_model=model, name="白")
        orders = [make_dealer_order(dealer, model, color, day) for day in (date(2026, 10, 8), date(2026, 10, 20))]
        rule = DealerVolumeBonusRule.objects.create(name="併發衝量", starts_on=OCT[0], ends_on=OCT[1])
        DealerVolumeBonusTier.objects.create(rule=rule, minimum_quantity=2, bonus_per_vehicle=500)
        recompute_rule(rule.pk, now=AFTER)
        scope = (rule.pk, rule.periods.get().pk, dealer.pk)
        barrier = Barrier(2)

        def settle(actor):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                settle_group(*scope, actor, now=AFTER)
                return "ok"
            except ValidationError:
                return "blocked"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(settle, actor) for actor in ("〔人員〕", "〔人員〕")]
            self.assertCountEqual([future.result(timeout=30) for future in futures], ["ok", "blocked"])
        self.assertEqual(VolumeBonusSettlement.objects.filter(cancelled_at__isnull=True).count(), 1)
        for order in orders:
            self.assertEqual(OrderOperationsProfile.objects.get(order=order).dealer_commission_expense, 2500)
        self.assertFalse(DealerPayoutEntry.objects.exists())
