"""T-315（使用者選 A）：訂單頁「領牌 → 車行獎勵」卡逐項勾已給付，與「車行傭金／獎金給付」頁同一筆紀錄。

- 寫入共用 `payouts.set_paid`（經 `set_order_paid`，只算這張單 `order_items`，不重算全公司）。
- 傭金與台數獎金分兩列；台數獎金整批發放，只顯示、拒絕勾選。實物獎勵每個活動×品項一列。
- 權限同給付頁「操作」；沒有的人看得到狀態，勾選框停用、POST 403。
- 勾選只影響給付登記，不動傭金、掛帳、淨利與收支。
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import (
    OrderAccountProfile, DealerRewardCampaign, DealerRewardCampaignItem, DealerRewardCatalogItem, DealerVolumeBonusRule,
    DealerVolumeBonusTier, OrderOperationsProfile, SalesOrder, SalesSource, VehicleBrand, VehicleColor, VehicleModel,
)
from sales.reporting import payouts
from sales.reporting.payout_models import DealerPayoutEntry, DealerPayoutEvent
from sales.services.dealer_commission import apply_order_dealer_commission, order_commission_display
from sales.services.dealer_reward_campaign import apply_order_dealer_rewards, order_dealer_rewards
from sales.services.dealer_settlement import dealer_settlement
from sales.services.volume_bonus import recompute_rule, settle_group
from sales.tests.test_dealer_payouts_t150 import KEY, PayoutTestBase
from sales.tests.test_legacy_payouts_t275 import LegacyPayoutBase


def card_html(client, order):
    page = client.get(reverse("order_detail", args=[order.pk]), {"tab": "registration"}).content.decode()
    if "data-order-dealer-rewards" not in page:
        return None
    return page.split("data-order-dealer-rewards", 1)[1].split("</section>", 1)[0]


def row_html(card, name):
    """卡片上名稱為 name 的那一列（<dt> 開頭就是名稱）。"""
    return card.split(f"<dt>{name}", 1)[1].split("data-order-payout-row", 1)[0]


class OrderPayoutBase(PayoutTestBase):
    def update(self, order, key, action="paid"):
        return self.client.post(reverse("order_dealer_payout_update", args=[order.pk]), {"key": key, "action": action})


class OrderItemsTests(OrderPayoutBase):
    def test_order_items_equal_collect_items_for_that_order_without_recomputing_company(self):
        order = self.registered()
        other = self.registered()
        everything = {item.source_key: item for item in payouts.collect_items() if item.order == order}
        with patch.object(payouts, "collect_items", side_effect=AssertionError("訂單頁不可重算全公司")):
            mine = payouts.order_items(order)
            payouts.set_order_paid(order, [KEY.format(order.pk)], True, "staffb")
        self.assertEqual([item.source_key for item in mine], list(everything))
        self.assertEqual([item.amount for item in mine], [item.amount for item in everything.values()])
        self.assertNotIn(KEY.format(other.pk), [item.source_key for item in mine])

    def test_set_paid_with_items_rejects_keys_outside_given_items(self):
        order, other = self.registered(), self.registered()
        with self.assertRaises(ValidationError):
            payouts.set_order_paid(order, [KEY.format(other.pk)], True, "staffb")
        self.assertFalse(DealerPayoutEntry.objects.exists())


class OrderPayoutSyncTests(OrderPayoutBase):
    def test_paid_on_order_is_paid_on_payout_page_and_back(self):
        order, other = self.registered(), self.registered()
        payouts.set_paid([KEY.format(other.pk)], True, "別人")
        self.client.force_login(self.admin)
        response = self.update(order, KEY.format(order.pk))
        self.assertRedirects(response, reverse("order_detail", args=[order.pk]) + "?tab=registration#order-dealer-rewards",
                             fetch_redirect_response=False)
        item = payouts.current_item(KEY.format(order.pk))
        self.assertTrue(item.paid)
        self.assertEqual((item.entry.paid_amount, item.entry.paid_by), (Decimal("2300"), "admin"))
        page = self.client.get(reverse("dealer_payout_list")).content.decode()
        self.assertIn(f'value="{KEY.format(order.pk)}"><input type="hidden" name="action" value="unpaid"', page)
        # 給付頁取消 → 訂單卡同步回未給付。
        payouts.set_paid([KEY.format(order.pk)], False, "staffb")
        row = row_html(card_html(self.client, order), "傭金")
        self.assertIn("payout-check__text\">未給付", row)
        self.assertIn('name="action" value="paid"', row)
        # 別張單的紀錄完全沒動。
        other_entry = DealerPayoutEntry.objects.get(source_key=KEY.format(other.pk))
        self.assertTrue(other_entry.paid)
        self.assertEqual(other_entry.events.count(), 1)

    def test_unpaid_from_order_keeps_history_and_card_shows_confirm(self):
        order = self.registered()
        self.client.force_login(self.admin)
        self.update(order, KEY.format(order.pk))
        row = row_html(card_html(self.client, order), "傭金")
        self.assertIn("payout-check__text\">已給付", row)
        self.assertIn("data-order-payout-confirm", row)
        self.assertIn("data-order-payout-panel", row)
        self.assertIn("只影響這張單的這一筆", row)
        self.assertIn("admin</b> 登記已給付", row)
        self.update(order, KEY.format(order.pk), "unpaid")
        entry = DealerPayoutEntry.objects.get(source_key=KEY.format(order.pk))
        self.assertFalse(entry.paid)
        self.assertEqual(list(entry.events.order_by("pk").values_list("action", flat=True)),
                         [DealerPayoutEvent.Action.PAID, DealerPayoutEvent.Action.UNPAID])
        self.assertEqual(entry.paid_amount, Decimal("2300"), "快照保留")

    def test_paid_does_not_touch_commission_settlement_or_ledger(self):
        order = self.registered(cash_receivable_v2=True)
        profile = OrderOperationsProfile.objects.get(order=order)
        before = (profile.dealer_commission_expense, dealer_settlement(order))
        payouts.set_order_paid(order, [KEY.format(order.pk)], True, "staffb")
        profile.refresh_from_db()
        self.assertEqual((profile.dealer_commission_expense, dealer_settlement(SalesOrder.objects.get(pk=order.pk))), before)

    def test_amount_changed_after_paid_links_to_payout_page(self):
        order = self.registered()
        payouts.set_order_paid(order, [KEY.format(order.pk)], True, "staffb")
        OrderOperationsProfile.objects.filter(order=order).update(
            dealer_commission_expense=2600, manual_financial_fields=["dealer_commission_expense"])
        self.client.force_login(self.admin)
        row = row_html(card_html(self.client, order), "傭金")
        self.assertIn("給付後金額有變：已付 $2,300，目前 $2,600", row)
        self.assertIn(reverse("dealer_payout_list") + f"?dealer={self.dealer.pk}&amp;status=changed", row)

    def test_get_does_not_write(self):
        order = self.registered()
        self.client.force_login(self.admin)
        card_html(self.client, order)
        self.assertFalse(DealerPayoutEntry.objects.exists())


class OrderPayoutCardTests(OrderPayoutBase):
    def setUp(self):
        self.helmet = DealerRewardCatalogItem.objects.create(reward_type="physical", name="安全帽", unit="頂")
        for name in ("年終衝量", "新車行首月禮"):
            campaign = DealerRewardCampaign.objects.create(
                name=name, brands=["SUZUKI"], effective_from=date(2026, 10, 1), effective_to=date(2026, 12, 31))
            DealerRewardCampaignItem.objects.create(
                campaign=campaign, catalog_item=self.helmet, reward_type="physical", name="安全帽", unit="頂", quantity=1)

    def test_each_campaign_item_is_its_own_checkable_row(self):
        order = self.registered()
        apply_order_dealer_rewards(order, force=True)
        keys = [item.source_key for item in payouts.order_items(order) if item.kind == "reward"]
        self.assertEqual(len(keys), 2)
        self.client.force_login(self.admin)
        card = card_html(self.client, order)
        rewards = card.split("data-dealer-reward-lines", 1)[1]
        self.assertEqual(rewards.count("<dt>安全帽"), 2)
        self.assertIn("年終衝量", rewards)
        self.assertIn("新車行首月禮", rewards)
        self.assertIn("已給付 0／3", card)
        payouts.set_order_paid(order, [keys[0]], True, "staffb")
        card = card_html(self.client, order)
        self.assertIn("已給付 1／3", card)
        paid_rows = [row for row in card.split("<dt>安全帽")[1:] if "payout-check__text\">已給付" in row.split("data-order-payout-row", 1)[0]]
        self.assertEqual(len(paid_rows), 1, "只勾了其中一個活動的安全帽")

    def test_pre_triggered_reward_is_checkable_but_commission_waits_for_registration(self):
        order = self.make_order(order_date=date(2026, 11, 1))
        SalesOrder.all_objects.filter(pk=order.pk).update(established_on=date(2026, 11, 1))
        order = SalesOrder.objects.get(pk=order.pk)
        apply_order_dealer_rewards(order, force=True)
        # 卡片要配車後才顯示（既有行為），這裡直接驗卡片資料。
        card = payouts.order_card(order, order_commission_display(order, order.operations), order_dealer_rewards(order))
        [commission] = card["commission_rows"]
        self.assertIsNone(commission["item"])
        self.assertEqual(commission["reason"], "確認領牌後才能登記給付")
        self.assertTrue(all(row["item"] is not None and row["item"].pre_triggered for row in card["reward_rows"]))
        self.assertEqual((card["paid_count"], card["total"]), (0, 2))
        self.client.force_login(self.admin)
        reward_key = next(item.source_key for item in payouts.order_items(order) if item.kind == "reward")
        self.assertEqual(self.update(order, reward_key).status_code, 302)
        self.assertTrue(DealerPayoutEntry.objects.get(source_key=reward_key).paid)
        with self.assertRaises(ValidationError):
            payouts.set_order_paid(order, [KEY.format(order.pk)], True, "staffb")

    def test_store_order_for_dealer_shows_commission_without_checkbox(self):
        order = self.registered(source_type="store", source=self.staff)
        SalesOrder.all_objects.filter(pk=order.pk).update(commission_recipient=self.dealer)
        OrderOperationsProfile.objects.filter(order=order).update(
            dealer_commission_expense=1200, manual_financial_fields=["dealer_commission_expense"])
        self.client.force_login(self.admin)
        commission = row_html(card_html(self.client, SalesOrder.objects.get(pk=order.pk)), "傭金")
        self.assertIn("本店單指定給車行的傭金，給付頁目前不列", commission)
        self.assertNotIn("data-order-payout-toggle", commission)


class OrderPayoutPermissionTests(OrderPayoutBase):
    """使用者 2026-11-24：能打開訂單頁的人都能在訂單卡上勾或取消（不需 dealer_payouts）；給付頁權限照舊。"""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        users = get_user_model().objects
        # 只有「訂單」查看權限：沒有訂單作業、沒有給付頁權限。
        cls.clerk = users.create_user("t315-clerk", password="Test-Only-123", first_name="小明", last_name="王")
        UserAccessState.objects.create(user=cls.clerk, configured=True)
        ScreenAccessGrant.objects.create(user=cls.clerk, screen_key="orders", view=True)
        # 只能看自己建的單（訂單範圍 own）。
        cls.own_only = users.create_user("t315-own", password="Test-Only-123")
        UserAccessState.objects.create(user=cls.own_only, configured=True)
        ScreenAccessGrant.objects.create(user=cls.own_only, screen_key="orders", view=True)
        OrderAccountProfile.objects.create(user=cls.own_only, order_scope="own")
        # 有給付頁權限、沒有訂單頁權限。
        cls.payout_only = users.create_user("t315-payout", password="Test-Only-123")
        UserAccessState.objects.create(user=cls.payout_only, configured=True)
        ScreenAccessGrant.objects.create(user=cls.payout_only, screen_key="dealer_payouts", view=True, operate=True)

    def test_anyone_who_can_open_order_can_check_and_history_names_them(self):
        order = self.registered()
        self.client.force_login(self.clerk)
        row = row_html(card_html(self.client, order), "傭金")
        self.assertNotIn(" disabled", row.split("data-order-payout-toggle", 1)[1].split(">", 1)[0])
        self.assertEqual(self.update(order, KEY.format(order.pk)).status_code, 302)
        entry = DealerPayoutEntry.objects.get()
        self.assertTrue(entry.paid)
        self.assertEqual(entry.paid_by, "小明 王")
        self.assertEqual(entry.events.get().actor_name, "小明 王")
        # 取消也可以；給付頁本身仍要 dealer_payouts 權限。
        self.assertEqual(self.update(order, KEY.format(order.pk), "unpaid").status_code, 302)
        self.assertFalse(DealerPayoutEntry.objects.get().paid)
        self.assertEqual(self.client.get(reverse("dealer_payout_list")).status_code, 403)
        self.assertEqual(self.client.post(reverse("dealer_payout_update"),
                                          {"action": "paid", "key": KEY.format(order.pk)}).status_code, 403)
        self.assertNotIn("在給付頁看這張單", card_html(self.client, order))

    def test_no_order_access_or_out_of_scope_or_anonymous_cannot_write(self):
        order = self.registered()
        # 沒有訂單頁權限（只有給付頁權限）：403。
        self.client.force_login(self.payout_only)
        self.assertEqual(self.update(order, KEY.format(order.pk)).status_code, 403)
        # 看不到這張單（訂單範圍只限自己建的）：與所有訂單頁網址相同，回 404、不透露訂單存在。
        self.client.force_login(self.own_only)
        self.assertEqual(self.client.get(reverse("order_detail", args=[order.pk])).status_code, 404)
        self.assertEqual(self.update(order, KEY.format(order.pk)).status_code, 404)
        # 沒有登入：導向登入頁。
        self.client.logout()
        response = self.update(order, KEY.format(order.pk))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])
        self.assertFalse(DealerPayoutEntry.objects.exists())


class OrderPayoutOverviewTests(OrderPayoutBase):
    """訂單總覽（T-307，快捷鍵 O）在「車行獎勵」區最後列唯讀的給付狀態；「複製全部」跟著帶（這一區本來就列傭金）。"""
    setUp = OrderPayoutCardTests.setUp

    @staticmethod
    def rows(overview):
        section = next(section for section in overview["sections"] if section["key"] == "dealer_reward")
        return {row["label"]: row for row in section["rows"]}

    def test_commission_and_reward_status_are_listed_read_only(self):
        from sales.services.order_overview import build_order_overview

        order = self.registered()
        apply_order_dealer_rewards(order, force=True)
        reward_key = next(item.source_key for item in payouts.order_items(order) if item.kind == "reward")
        payouts.set_order_paid(order, [KEY.format(order.pk), reward_key], True, "王小明")
        today = timezone.localtime().strftime("%m/%d")
        overview = build_order_overview(SalesOrder.objects.get(pk=order.pk))
        rows = self.rows(overview)
        self.assertEqual(rows["傭金給付"]["value"], f"傭金 $2,300 · 已給付（{today} 王小明）")
        self.assertEqual(rows["活動獎勵給付"]["value"],
                         f"安全帽（年終衝量）1 頂 · 已給付（{today} 王小明）、安全帽（新車行首月禮）1 頂 · 未給付")
        self.assertIn(f"傭金給付：傭金 $2,300 · 已給付（{today} 王小明）", overview["plain_text"])
        self.assertIn("活動獎勵給付：安全帽（年終衝量）", overview["plain_text"])
        # 既有列不變（T-258）。
        self.assertEqual(rows["傭金"]["value"], "$2,300（預估）")
        # 沒有傭金權限：不列傭金給付，實物照列。
        rows = self.rows(build_order_overview(SalesOrder.objects.get(pk=order.pk), include_finance=False))
        self.assertNotIn("傭金給付", rows)
        self.assertIn("已給付", rows["活動獎勵給付"]["value"])
        # 總覽頁只顯示、不能勾。
        self.client.force_login(self.admin)
        page = self.client.get(reverse("order_overview", args=[order.pk])).content.decode()
        self.assertIn('data-label="傭金給付"', page)
        self.assertNotIn("data-order-payout-toggle", page)

    def test_unlisted_and_empty_orders(self):
        from sales.services.order_overview import build_order_overview

        order = self.make_order(order_date=date(2026, 11, 1))
        rows = self.rows(build_order_overview(SalesOrder.objects.get(pk=order.pk)))
        self.assertEqual(rows["傭金給付"]["value"], "傭金 $2,300 · 確認領牌後才能登記給付")
        self.assertEqual((rows["活動獎勵給付"]["value"], rows["活動獎勵給付"]["copy"]), ("—", ""))


class OrderPayoutVolumeBonusTests(TestCase):
    """台數獎金是同車行、同期間多張單合成一筆：訂單上只顯示（附給付頁連結），勾選一律拒絕。"""
    AFTER = timezone.make_aware(datetime(2026, 11, 1, 4))

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", password="Test-Only-123")
        cls.dealer = SalesSource.objects.create(name="示範車行丙", source_type="dealer")
        VehicleBrand.objects.get_or_create(name="SUZUKI")
        cls.model = VehicleModel.objects.create(brand="SUZUKI", name="SUI", energy_type="gas", base_dealer_commission=1500)
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="黑")

    def order(self, day):
        order = SalesOrder.objects.create(
            source=self.dealer, source_type="dealer", order_date=day, owner_type="company", owner_name="測試公司",
            owner_id_number="83739807", owner_phone="0912345678", owner_address="測試地址", vehicle_model=self.model,
            color=self.color, vehicle_price=70000, actual_balance=70000, calculated_balance=70000, payment_type="cash",
            registration_date=day, registration_completed_at=timezone.now(), status="delivery_pending")
        apply_order_dealer_commission(order, lock=True)
        return order

    def settled(self):
        first, second = self.order(date(2026, 10, 8)), self.order(date(2026, 10, 20))
        rule = DealerVolumeBonusRule.objects.create(name="十月衝量", starts_on=date(2026, 10, 1), ends_on=date(2026, 10, 31))
        DealerVolumeBonusTier.objects.create(rule=rule, minimum_quantity=2, bonus_per_vehicle=500)
        recompute_rule(rule.pk, now=self.AFTER)
        settle_group(rule.pk, rule.periods.get().pk, self.dealer.pk, "staffb", now=self.AFTER)
        return first, second

    def test_commission_and_bonus_are_two_rows_bonus_read_only(self):
        first, _second = self.settled()
        self.assertEqual(OrderOperationsProfile.objects.get(order=first).dealer_commission_expense, Decimal("2000"))
        self.client.force_login(self.admin)
        card = card_html(self.client, first)
        commission = row_html(card, "傭金")
        bonus = row_html(card, "台數獎金")
        self.assertIn("$1,500", commission)
        self.assertIn("data-order-payout-toggle", commission)
        self.assertIn("$500", bonus)
        self.assertIn("2 台合計 $1,000，整批付給車行", bonus)
        self.assertIn("整批發放", bonus)
        self.assertNotIn("data-order-payout-toggle", bonus)
        self.assertIn(f"?dealer={self.dealer.pk}&amp;kind=volume_bonus", bonus)
        self.assertIn("傭金＋台數獎金＝$2,000，與「收入與支出」的傭金支出同一筆", card)
        self.assertIn("已給付 0／1", card, "台數獎金不算在可勾的項目裡")
        from sales.services.order_overview import build_order_overview
        section = next(section for section in build_order_overview(SalesOrder.objects.get(pk=first.pk))["sections"]
                       if section["key"] == "dealer_reward")
        paid_row = next(row for row in section["rows"] if row["label"] == "傭金給付")
        self.assertEqual(paid_row["value"], "傭金 $1,500 · 未給付；台數獎金 $500 · 待發放（整批發放）")

    def test_bonus_key_is_rejected_from_order(self):
        first, second = self.settled()
        [bonus] = [item for item in payouts.order_items(first) if item.kind == "volume_bonus"]
        with self.assertRaises(ValidationError):
            payouts.set_order_paid(first, [bonus.source_key], True, "staffb")
        self.client.force_login(self.admin)
        response = self.client.post(reverse("order_dealer_payout_update", args=[first.pk]),
                                    {"key": bonus.source_key, "action": "paid"}, follow=True)
        self.assertContains(response, "台數獎金是整批發放")
        self.assertFalse(DealerPayoutEntry.objects.exists())
        # 給付頁照舊可以整批勾；訂單卡跟著顯示已發放，但仍不能從訂單取消。
        payouts.set_paid([bonus.source_key], True, "staffb")
        self.assertIn("已發放", row_html(card_html(self.client, second), "台數獎金"))
        with self.assertRaises(ValidationError):
            payouts.set_order_paid(second, [bonus.source_key], False, "staffb")
        self.assertTrue(DealerPayoutEntry.objects.get(source_key=bonus.source_key).paid)


class OrderPayoutLegacyTests(LegacyPayoutBase):
    def test_prior_settled_import_shows_settled_and_undo_creates_entry(self):
        order = self.imported()
        self.client.force_login(self.admin)
        row = row_html(card_html(self.client, order), "傭金")
        self.assertIn("payout-check__text\">已結清", row)
        self.assertIn("推定匯入前已和車行結清", row)
        self.assertIn("給付頁金額 $6,200", row)
        self.assertIn("其實還沒付？", row)
        payouts.set_order_paid(order, [KEY.format(order.pk)], True, "staffb")
        self.assertFalse(DealerPayoutEntry.objects.exists(), "勾已給付不寫入（T-275）")
        payouts.set_order_paid(order, [KEY.format(order.pk)], False, "staffb")
        entry = DealerPayoutEntry.objects.get(source_key=KEY.format(order.pk))
        self.assertFalse(entry.paid)
        self.assertEqual(payouts.current_item(KEY.format(order.pk)).status, "unpaid")


@skipUnless(connection.vendor == "postgresql", "需 PostgreSQL 驗證列鎖")
class OrderPayoutConcurrencyTests(TransactionTestCase):
    """訂單頁與給付頁兩人同時勾同一列：只會有一筆給付紀錄、一筆「標記已給付」歷程（沿用 _locked_entry）。"""

    def test_order_and_payout_page_marking_same_item_create_one_entry(self):
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

        def mark(from_order):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                if from_order:
                    return payouts.set_order_paid(SalesOrder.objects.get(pk=order.pk), [key], True, "訂單頁")
                return payouts.set_paid([key], True, "給付頁")
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(mark, flag) for flag in (True, False)]
            self.assertCountEqual([future.result(timeout=30) for future in futures], [1, 0])
        self.assertEqual(DealerPayoutEntry.objects.filter(source_key=key).count(), 1)
        self.assertEqual(DealerPayoutEvent.objects.filter(entry__source_key=key, action="paid").count(), 1)
