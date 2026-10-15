"""1.80.0：已交車→已結案改由人員確認；補助只分未申請／已申請；網路平台訂單不帶車價。"""
from django.test import TestCase
from django.urls import reverse

from sales.models import OrderEvent, SalesOrder, SalesSource, SubsidyItem
from sales.services import order_tabs
from sales.services.subsidy_summary import agency_summary
from sales.tests import test_order_intake as intake_fixtures


class OrderCloseTests(TestCase):
    image = intake_fixtures.OrderIntakeTests.image
    complete_data = intake_fixtures.OrderIntakeTests.complete_data
    setUp = intake_fixtures.OrderIntakeTests.setUp

    def create_order(self, **changes):
        data = self.complete_data()
        data.update(id_front=self.image("front.png"), id_back=self.image("back.png"))
        data.update(changes)
        response = self.client.post(reverse("order_create"), data)
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        return SalesOrder.objects.latest("pk")

    def tab_numbers(self, key):
        orders = order_tabs.with_subsidy_progress(SalesOrder.objects.all())
        return set(orders.filter(order_tabs.tab_filter(key)).values_list("number", flat=True))

    def test_delivered_order_stays_delivered_until_someone_closes_it(self):
        order = self.create_order()
        SalesOrder.objects.filter(pk=order.pk).update(status=SalesOrder.Status.COMPLETED)
        self.assertIn(order.number, self.tab_numbers("delivered"))
        self.assertNotIn(order.number, self.tab_numbers("closed"))
        order.refresh_from_db()
        self.assertEqual(order.display_status, "已交車／待結案")

        response = self.client.post(reverse("order_close", args=[order.pk]))
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertTrue(order.closed_at)
        self.assertIn(order.number, self.tab_numbers("closed"))
        self.assertNotIn(order.number, self.tab_numbers("delivered"))
        self.assertTrue(OrderEvent.objects.filter(order=order, event_type="order_closed").exists())

        self.client.post(reverse("order_close", args=[order.pk]), {"action": "reopen"})
        order.refresh_from_db()
        self.assertIsNone(order.closed_at)
        self.assertIn(order.number, self.tab_numbers("delivered"))
        self.assertTrue(OrderEvent.objects.filter(order=order, event_type="order_reopened").exists())

    def test_close_has_no_document_or_subsidy_gate(self):
        # 使用者 2026-10-15：按了就給過，不檢查文件或補助。
        order = self.create_order()
        SalesOrder.objects.filter(pk=order.pk).update(
            status=SalesOrder.Status.DELIVERED_DOCS_PENDING, is_trade_in_subsidy=True,
        )
        SubsidyItem.objects.create(order=order, category=SubsidyItem.Category.LOCAL, item_name="汰舊", expected_amount=1000)
        self.client.post(reverse("order_close", args=[order.pk]))
        order.refresh_from_db()
        self.assertTrue(order.closed_at)
        self.assertIn(order.number, self.tab_numbers("closed"))

    def test_undelivered_order_cannot_be_closed(self):
        order = self.create_order()
        self.client.post(reverse("order_close", args=[order.pk]))
        order.refresh_from_db()
        self.assertIsNone(order.closed_at)

    def test_subsidy_status_is_only_not_applied_or_applied(self):
        self.assertEqual([value for value, _label in SubsidyItem.Status.choices], ["not_submitted", "submitted"])
        self.assertEqual(SubsidyItem.Status.SUBMITTED.label, "已申請")
        order = self.create_order()
        items = [
            SubsidyItem.objects.create(order=order, category=SubsidyItem.Category.LOCAL, item_name="一", expected_amount=100,
                                       status=SubsidyItem.Status.SUBMITTED),
            SubsidyItem.objects.create(order=order, category=SubsidyItem.Category.LOCAL, item_name="二", expected_amount=200),
        ]
        local = next(row for row in agency_summary(items) if row["category"] == SubsidyItem.Category.LOCAL)
        self.assertEqual(local["progress"], "已申請 1／2 筆")
        orders = order_tabs.with_subsidy_progress(SalesOrder.objects.filter(pk=order.pk))
        self.assertEqual(orders.get().pending_subsidy_count, 1)

    def test_platform_order_has_no_payment_choice_or_vehicle_price(self):
        platform = SalesSource.objects.create(name="某購物平台", source_type="platform")
        order = self.create_order(
            source_type="platform", source=str(platform.pk), payment_type="installment",
            vehicle_price="79800", vehicle_price_adjustment_reason="不應保存",
        )
        self.assertEqual(order.payment_type, SalesOrder.PaymentType.CASH)
        self.assertEqual(order.vehicle_price, 0)
        self.assertEqual(order.vehicle_price_adjustment_reason, "")
        # 客人只付牌險、選號、其他費用與配件（扣訂金），不含車款。
        self.assertEqual(
            order.pre_discount_total,
            order.plate_insurance_fee + order.registration_extra_fee_total + order.other_fee_total
            + order.old_vehicle_tax + order.accessory_total,
        )
