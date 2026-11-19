"""T-148：台數獎金依規則自動計算、適用車行可複選（每家各自計算）。

使用者 2026-11-11：選 B ＋ Y（多選車行各自計算）；人工傭金保留。
T-203（使用者 2026-11-17 選 C）取代「期間結束自動入帳」：期間結束後仍是試算，要在給付頁按「結算」才加進傭金支出；
結算後另外發放給車行，不扣應收或掛帳。結算本身的測試在 test_volume_bonus_settle_t203.py。
"""
from datetime import date, datetime, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from sales.forms import DealerVolumeBonusRuleForm
from sales.models import (
    DealerVolumeBonusRule,
    DealerVolumeBonusRuleDealer,
    DealerVolumeBonusTier,
    OrderEvent,
    OrderOperationsProfile,
    OrderVolumeBonus,
    SalesOrder,
    SalesSource,
    VehicleBrand,
    VehicleColor,
    VehicleModel,
)
from sales.services.dealer_commission import apply_order_dealer_commission, dealer_volume_bonus_total
from sales.services.dealer_settlement import dealer_settlement
from sales.services.volume_bonus import cancel_settlement, recompute_rule, settle_group, sync_all

SEPT = (date(2026, 9, 1), date(2026, 9, 30))
DURING = timezone.make_aware(datetime(2026, 9, 20, 10))
AFTER = timezone.make_aware(datetime(2026, 10, 1, 4))


class VolumeBonusAutoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser("admin", password="Test-Only-123")
        cls.a = SalesSource.objects.create(name="自動 A 車行", source_type="dealer")
        cls.b = SalesSource.objects.create(name="自動 B 車行", source_type="dealer")
        cls.c = SalesSource.objects.create(name="自動 C 車行", source_type="dealer")
        VehicleBrand.objects.get_or_create(name="SUZUKI")
        cls.model = VehicleModel.objects.create(brand="SUZUKI", name="自動獎金車", energy_type="gas", base_dealer_commission=2000)
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="白")

    def order(self, dealer, **overrides):
        values = dict(source=dealer, source_type="dealer", order_date=date(2026, 9, 1),
                      owner_type="company", owner_name="測試公司", owner_id_number="83739807", owner_phone="0912345678",
                      owner_address="測試地址", vehicle_model=self.model, color=self.color, vehicle_price=70000,
                      actual_balance=70000, calculated_balance=70000, payment_type="cash",
                      registration_date=date(2026, 9, 3), registration_completed_at=timezone.now(), status="delivery_pending")
        values.update(overrides)
        order = SalesOrder.objects.create(**values)
        apply_order_dealer_commission(order, lock=True)
        return order

    def rule(self, dealers=(), minimum=2, amount=500, **fields):
        rule = DealerVolumeBonusRule.objects.create(name="自動獎金", starts_on=SEPT[0], ends_on=SEPT[1], **fields)
        DealerVolumeBonusTier.objects.create(rule=rule, minimum_quantity=minimum, bonus_per_vehicle=amount)
        for dealer in dealers:
            DealerVolumeBonusRuleDealer.objects.create(rule=rule, dealer=dealer)
        return rule

    def expense(self, order):
        return OrderOperationsProfile.objects.get(order=order).dealer_commission_expense

    def settle(self, rule, dealer=None):
        return settle_group(rule.pk, rule.periods.get().pk, (dealer or self.a).pk, "staffb", now=AFTER)

    def test_multi_dealer_rule_counts_each_dealer_separately(self):
        a1, a2, b1 = self.order(self.a), self.order(self.a), self.order(self.b)
        c1, c2 = self.order(self.c), self.order(self.c)
        rule = self.rule(dealers=[self.a, self.b])
        recompute_rule(rule.pk, now=AFTER)
        rows = {row.order_id: row for row in OrderVolumeBonus.objects.filter(rule=rule)}
        self.assertEqual(set(rows), {a1.pk, a2.pk})  # B 只有 1 台未達 2 台門檻；C 不在名單
        self.assertEqual(rows[a1.pk].quantity, 2)
        self.assertEqual(rows[a1.pk].amount, 500)
        self.assertEqual(self.expense(b1), 2000)
        self.assertEqual(self.expense(c1), 2000)
        self.assertEqual(self.expense(c2), 2000)

    def test_bonus_stays_trial_after_period_ends_until_settled(self):
        a1, a2 = self.order(self.a), self.order(self.a)
        rule = self.rule()
        recompute_rule(rule.pk, now=DURING)
        self.assertTrue(OrderVolumeBonus.objects.filter(rule=rule, posted_at__isnull=True).count() == 2)
        self.assertEqual(self.expense(a1), 2000)  # 期間內只是試算，不進傭金支出
        sync_all(now=AFTER)
        # T-203：期間結束也不自動入帳，要按結算。
        self.assertEqual(OrderVolumeBonus.objects.filter(rule=rule, posted_at__isnull=False).count(), 0)
        self.assertEqual(self.expense(a1), 2000)
        self.assertFalse(OrderEvent.objects.filter(order=a1, event_type="volume_bonus_adjusted").exists())
        self.settle(rule)
        self.assertEqual(self.expense(a1), 2500)
        self.assertEqual(self.expense(a2), 2500)
        self.assertEqual(dealer_volume_bonus_total(a1), 500)
        self.assertEqual(sync_all(now=AFTER), 0)  # 冪等

    def test_trial_recomputes_when_order_leaves_group(self):
        a1, a2 = self.order(self.a), self.order(self.a)
        rule = self.rule()
        recompute_rule(rule.pk, now=AFTER)
        self.assertEqual(OrderVolumeBonus.objects.filter(rule=rule).count(), 2)
        with self.captureOnCommitCallbacks(execute=True):
            a2.registration_date = date(2026, 10, 2)  # 改領牌日移出期間 → A 剩 1 台、不達門檻
            a2.save()
        self.assertEqual(self.expense(a1), 2000)
        self.assertEqual(self.expense(a2), 2000)
        self.assertFalse(OrderVolumeBonus.objects.filter(rule=rule).exists())

    def test_order_joining_group_lifts_existing_orders_to_higher_tier(self):
        a1, a2 = self.order(self.a), self.order(self.a)
        rule = self.rule()
        DealerVolumeBonusTier.objects.create(rule=rule, minimum_quantity=3, bonus_per_vehicle=800)
        recompute_rule(rule.pk, now=AFTER)
        with self.captureOnCommitCallbacks(execute=True):
            a3 = self.order(self.a)
        self.assertEqual(set(OrderVolumeBonus.objects.filter(rule=rule).values_list("amount", flat=True)), {800})
        self.settle(rule)
        for order in (a1, a2, a3):
            self.assertEqual(self.expense(order), 2800)

    def test_manual_commission_is_kept(self):
        a1, a2 = self.order(self.a), self.order(self.a)
        profile = OrderOperationsProfile.objects.get(order=a1)
        profile.dealer_commission_expense = 1234
        profile.manual_financial_fields = ["dealer_commission_expense"]
        profile.save()
        rule = self.rule()
        recompute_rule(rule.pk, now=AFTER)
        self.settle(rule)
        self.assertEqual(self.expense(a1), 1234)
        self.assertEqual(self.expense(a2), 2500)
        self.assertTrue(OrderVolumeBonus.objects.filter(order=a1, posted_at__isnull=False).exists())

    def test_bonus_is_paid_to_dealer_not_deducted_from_order_receivable(self):
        a1, _a2 = self.order(self.a, cash_receivable_v2=True), self.order(self.a, cash_receivable_v2=True)
        from sales.services.customer_receivable import dealer_cash_credit
        before = dealer_cash_credit(a1)
        rule = self.rule()
        recompute_rule(rule.pk, now=AFTER)
        self.settle(rule)
        a1.refresh_from_db()
        settlement = dealer_settlement(a1)
        self.assertEqual(settlement["volume_bonus"], 500)
        self.assertEqual(dealer_cash_credit(a1), before)  # 應收不變，不會變成溢收
        self.assertEqual(settlement["total"], before)  # T-203：結算卡也不扣台數獎金，和掛帳一致

    def test_inactive_rule_keeps_settled_bonus_until_cancelled(self):
        a1, _a2 = self.order(self.a), self.order(self.a)
        rule = self.rule()
        recompute_rule(rule.pk, now=AFTER)
        self.settle(rule)
        self.assertEqual(self.expense(a1), 2500)
        rule.active = False
        rule.save()
        recompute_rule(rule.pk, now=AFTER)
        self.assertEqual(self.expense(a1), 2500)  # 已結算金額固定，停用只標「結算後有變」
        cancel_settlement(rule.pk, rule.periods.get().pk, self.a.pk, "staffb", now=AFTER)
        self.assertEqual(self.expense(a1), 2000)
        self.assertFalse(OrderVolumeBonus.objects.filter(rule=rule).exists())  # 停用的規則不再試算
        with self.captureOnCommitCallbacks(execute=True):
            rule.delete()
        self.assertEqual(self.expense(a1), 2000)

    def test_legacy_single_dealer_field_becomes_dealer_list(self):
        rule = DealerVolumeBonusRule.objects.create(name="舊單選", dealer=self.b, starts_on=SEPT[0], ends_on=SEPT[1])
        self.assertEqual([link.dealer for link in rule.dealer_links.all()], [self.b])
        self.assertEqual(rule.dealers_label, self.b.name)

    def test_rule_form_saves_multiple_dealers(self):
        data = {"name": "多車行", "dealers": [str(self.a.pk), str(self.b.pk)], "brands": ["SUZUKI"], "energy_type": "",
                "period_type": "custom", "starts_on": "2026-09-01", "ends_on": "2026-09-30", "active": "on", "note": "",
                "period_selection_version": "2"}
        form = DealerVolumeBonusRuleForm(data, instance=DealerVolumeBonusRule())
        self.assertTrue(form.is_valid(), form.errors)
        rule = form.save()
        self.assertEqual({link.dealer_id for link in rule.dealer_links.all()}, {self.a.pk, self.b.pk})
        self.assertIsNone(rule.dealer_id)  # 多選不寫舊單選欄位
        self.assertIn("逐家計算", rule.dealers_label)
        edit = DealerVolumeBonusRuleForm({**data, "dealers": [str(self.b.pk)]}, instance=rule)
        self.assertTrue(edit.is_valid(), edit.errors)
        rule = edit.save()
        self.assertEqual([link.dealer_id for link in rule.dealer_links.all()], [self.b.pk])
        self.assertEqual(rule.dealer_id, self.b.pk)

    def test_trial_pages_are_read_only_and_settlement_routes_are_gone(self):
        self.order(self.a), self.order(self.a)
        rule = self.rule(dealers=[self.a, self.b])
        self.client.force_login(self.user)
        listing = self.client.get(reverse("dealer_volume_bonus_list") + "?tab=trial&show=all")
        self.assertContains(listing, "台數試算")
        self.assertNotContains(listing, "確認結算")
        self.assertContains(listing, "逐單明細")
        old = self.client.get(reverse("dealer_volume_bonus_list") + "?tab=settlements")
        self.assertContains(old, 'aria-current="page">台數試算')
        period = rule.periods.get()
        detail = self.client.get(reverse("dealer_volume_bonus_detail", args=[rule.pk]) + f"?period={period.pk}&dealer={self.a.pk}")
        self.assertContains(detail, "本期獎金")
        self.assertContains(detail, "2 台")
        self.assertNotContains(detail, "確認結算")
        self.assertNotContains(detail, 'method="post" class="stacked-form"')
        form_page = self.client.get(reverse("dealer_volume_bonus_edit", args=[rule.pk]))
        self.assertContains(form_page, 'name="dealers"')
        self.assertContains(form_page, "multiple")
        for name in ("dealer_volume_bonus_settle", "dealer_volume_bonus_revise"):
            with self.assertRaises(NoReverseMatch):
                reverse(name, args=[1])
