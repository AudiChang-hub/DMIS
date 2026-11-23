"""T-298：一定先領牌才交車，車行單也一樣（使用者 2026-11-23 選 A）。

取消車行單未領牌先交車的例外；交車一律轉已完成；確認結案也要先確認領牌（Excel 匯入單不擋）；
營運總表拿掉「交車待文件」這一站；車行到期提醒只剩尾款。狀態值 `delivered_docs_pending` 保留不刪。"""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.forms import DeliveryCompletionForm
from sales.models import LegacyImportBatch, LegacyImportRow, LegacySalesSnapshot, SalesOrder
from sales.services import operations_cockpit
from sales.services.business_days import build_dealer_reminders
from sales.services.order_next_actions import build_order_next_actions
from sales.tests import test_order_lifecycle as lifecycle
from sales.tests.test_money_card_t278 import MoneyCardTestBase

GENERIC_BLOCKER = "須先完成領牌確認才能交付。"


class DeliveryRequiresRegistrationTests(TestCase):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order
    delivery_payload = lifecycle.OrderLifecycleTests.delivery_payload

    def register(self, order):
        SalesOrder.objects.filter(pk=order.pk).update(
            registration_completed_at=timezone.now(), status=SalesOrder.Status.DELIVERY_PENDING)
        return SalesOrder.objects.get(pk=order.pk)

    def test_dealer_order_cannot_deliver_before_registration(self):
        order, _vehicle = self.make_order(dealer=True)
        self.assertFalse(order.can_deliver)
        self.assertIn(GENERIC_BLOCKER, order.delivery_blockers())
        form = DeliveryCompletionForm(order, self.delivery_payload())
        self.assertTrue(form.is_valid(), form.errors)
        with self.assertRaisesMessage(ValidationError, GENERIC_BLOCKER):
            form.save("測試人員")
        order.refresh_from_db()
        self.assertEqual(order.status, SalesOrder.Status.ALLOCATED)
        self.assertIsNone(order.delivered_at)

    def test_blocker_text_is_the_same_for_every_channel(self):
        store, _vehicle = self.make_order()
        dealer, _vehicle = self.make_order(dealer=True)
        self.assertIn(GENERIC_BLOCKER, store.delivery_blockers())
        self.assertIn(GENERIC_BLOCKER, dealer.delivery_blockers())
        self.assertFalse(any("一般訂單" in item for item in store.delivery_blockers() + dealer.delivery_blockers()))

    def test_delivery_always_completes_the_order(self):
        for dealer in (True, False):
            with self.subTest(dealer=dealer):
                order = self.register(self.make_order(dealer=dealer, deposit=Decimal("75000"))[0])
                order.complete_delivery(timezone.now(), "測試")
                order.refresh_from_db()
                self.assertEqual(order.status, SalesOrder.Status.COMPLETED)

    def test_no_transition_enters_delivered_docs_pending_but_leaving_still_works(self):
        docs = SalesOrder.Status.DELIVERED_DOCS_PENDING
        for source, targets in SalesOrder.STATUS_TRANSITIONS.items():
            self.assertNotIn(docs, targets, source)
        self.assertEqual(SalesOrder.STATUS_TRANSITIONS[docs],
                         {SalesOrder.Status.COMPLETED, SalesOrder.Status.EXCEPTION_CLOSED})
        self.assertIn(docs, SalesOrder.Status.values)   # 選項保留，不做 migration

    def test_dealer_next_actions_no_longer_offer_early_delivery(self):
        order, _vehicle = self.make_order(dealer=True)
        actions = build_order_next_actions(order)
        self.assertEqual(actions.primary.key, "registration")
        self.assertNotIn("dealer-early-delivery", [action.key for action in actions.all_actions])

    def test_dealer_order_page_keeps_delivery_closed_until_registered(self):
        order, _vehicle = self.make_order(dealer=True)
        self.client.force_login(self.user)
        page = self.client.get(f"{reverse('order_detail', args=[order.pk])}?tab=delivery").content.decode()
        self.assertNotIn('id="delivery-completion-form"', page)
        self.assertNotIn("可先交付車輛", page)
        self.assertIn(GENERIC_BLOCKER, page)


class CloseRequiresRegistrationTests(TestCase):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def delivered_without_registration(self):
        order, _vehicle = self.make_order(dealer=True)
        SalesOrder.objects.filter(pk=order.pk).update(
            status=SalesOrder.Status.DELIVERED_DOCS_PENDING, delivered_at=timezone.now())
        return SalesOrder.objects.get(pk=order.pk)

    def test_unregistered_order_cannot_be_closed(self):
        order = self.delivered_without_registration()
        with self.assertRaisesMessage(ValidationError, "尚未確認領牌的訂單不能結案"):
            order.mark_closed("測試")
        self.client.force_login(self.user)
        self.client.post(reverse("order_close", args=[order.pk]))
        order.refresh_from_db()
        self.assertIsNone(order.closed_at)

    def test_registered_order_can_be_closed(self):
        order = self.delivered_without_registration()
        SalesOrder.objects.filter(pk=order.pk).update(
            status=SalesOrder.Status.COMPLETED, registration_completed_at=timezone.now())
        order = SalesOrder.objects.get(pk=order.pk)
        order.mark_closed("測試")
        order.refresh_from_db()
        self.assertIsNotNone(order.closed_at)

    def test_imported_history_order_is_not_blocked(self):
        order = self.delivered_without_registration()
        SalesOrder.objects.filter(pk=order.pk).update(status=SalesOrder.Status.COMPLETED)
        batch = LegacyImportBatch.objects.create(import_type="operations", original_filename="t298.xlsx", file_size=0)
        row = LegacyImportRow.objects.create(batch=batch, sheet_name="銷貨", source_row=order.pk,
                                             fingerprint=f"t298-close-{order.pk}")
        LegacySalesSnapshot.objects.create(order=order, import_row=row)
        order = SalesOrder.objects.get(pk=order.pk)
        self.assertFalse(order.is_registration_complete)
        order.mark_closed("測試")
        order.refresh_from_db()
        self.assertIsNotNone(order.closed_at)


class CockpitWithoutDocsStageTests(MoneyCardTestBase):
    def test_flow_has_no_delivered_docs_pending_stage(self):
        self.assertNotIn("delivered_docs_pending", operations_cockpit.STAGE_LIMITS)
        old = self.order("delivered_docs_pending", timezone.now() - timedelta(days=60),
                         source_type="dealer", source=self.dealer)
        stages = operations_cockpit.build("month", self.today)["flow"]["stages"]
        self.assertEqual([stage["key"] for stage in stages], ["allocation_pending", "allocated", "delivery_pending"])
        self.assertNotIn(old.pk, operations_cockpit.stuck_order_ids(self.today))
        response, _cockpit = self.cockpit()
        self.assertNotContains(response, "交車待文件")

    def test_dealer_due_reminds_only_balance(self):
        long_ago = timezone.now() - timedelta(days=30)
        owing = self.order("completed", long_ago, source_type="dealer", source=self.dealer)
        settled = self.settle(self.order("completed", long_ago, source_type="dealer", source=self.dealer))
        reminders = build_dealer_reminders(self.today)
        kinds = {(item["order"].pk, item["kind"]) for item in reminders}
        self.assertIn((owing.pk, "dealer_balance"), kinds)          # 尾款到期提醒保留
        self.assertEqual({kind for _pk, kind in kinds}, {"dealer_balance"})
        self.assertNotIn(settled.pk, {pk for pk, _kind in kinds})    # 沒有領牌文件的提醒了
        item = self.attention()["dealer_due"]
        self.assertEqual(item["label"], "車行尾款到期")
        self.assertEqual(item["value"], 1)
        self.assertNotIn("領牌", item["detail"])
        self.assertEqual(self.listed({"attention": "dealer"}), {owing.pk})
