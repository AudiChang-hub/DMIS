"""使用者 2026-11-09 T-138 p4：實際交付時間改選填，「不要補時間，留空」。

留空時：不自動補現在、車行 3 個工作天領牌期限不起算（改提示未填交付時間）、配車保留逾期不誤算、
訂單頁／總覽／步驟摘要／報表與匯出都照常。"""
from django.test import TestCase
from django.urls import reverse

from sales.forms import DeliveryCompletionForm
from sales.models import SalesOrder
from sales.services.business_days import build_dealer_reminders
from sales.services.order_next_actions import build_order_next_actions
from sales.services.order_overview import build_order_overview
from sales.services.order_steps import build_order_steps
from sales.services.sales_metrics import filter_payment_risk
from sales.tests import test_order_lifecycle as lifecycle


class BlankDeliveryTimeTests(TestCase):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order
    delivery_payload = lifecycle.OrderLifecycleTests.delivery_payload

    def deliver_blank(self):
        order, _vehicle = self.make_order(dealer=True)
        form = DeliveryCompletionForm(order, {**self.delivery_payload(), "delivered_at": ""})
        self.assertFalse(form.fields["delivered_at"].required)
        self.assertTrue(form.is_valid(), form.errors)
        form.save("測試人員")
        return SalesOrder.objects.get(pk=order.pk)

    def test_blank_time_stays_blank_after_delivery_and_later_saves(self):
        order = self.deliver_blank()
        self.assertEqual(order.status, SalesOrder.Status.DELIVERED_DOCS_PENDING)
        self.assertIsNone(order.delivered_at)
        self.assertEqual(order.delivered_by, "測試人員")
        order.save()
        order.refresh_from_db()
        self.assertIsNone(order.delivered_at)

    def test_dealer_document_deadline_does_not_start(self):
        order = self.deliver_blank()
        action = build_order_next_actions(order).primary
        self.assertEqual(action.key, "registration")
        self.assertEqual(action.badge, "未填交付時間")
        self.assertEqual(action.tone, "primary")
        self.assertIn("未填交付時間，期限不起算", action.description)
        self.assertNotIn(order.pk, [item["order"].pk for item in build_dealer_reminders()
                                    if item["kind"] == "registration_documents"])

    def test_delivered_order_is_not_counted_as_stale_allocation(self):
        order = self.deliver_blank()
        SalesOrder.objects.filter(pk=order.pk).update(allocated_at=order.created_at.replace(year=2020))
        self.assertFalse(filter_payment_risk(SalesOrder.objects.all(), "stale_allocation").filter(pk=order.pk).exists())

    def test_order_page_overview_and_steps_render_without_time(self):
        order = self.deliver_blank()
        self.assertEqual(build_order_steps(order)["steps"]["delivery"]["summary"], "已交付")
        rows = [row for section in build_order_overview(order)["sections"] for row in section["rows"] if row["label"] == "交車完成"]
        self.assertEqual(rows[0]["value"], "測試人員")
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[order.pk]))
        self.assertContains(page, "已完成交付（時間未記錄）")

    def test_delivery_form_shows_time_as_optional(self):
        order, _vehicle = self.make_order(dealer=True)
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        self.assertRegex(page, r'<label for="id_delivered_at">實際交付時間</label>')
        self.assertIn('data-lock-required="recipient_name handover_location', page)
        self.assertNotIn('data-lock-required="delivered_at', page)

    def test_reports_and_export_filter_by_delivery_date_skip_blank(self):
        order = self.deliver_blank()
        self.client.force_login(self.user)
        listed = self.client.get(reverse("order_list"), {"date_basis": "delivery", "date_from": "2026-01-01"})
        self.assertEqual(listed.status_code, 200)
        self.assertNotContains(listed, order.number)
        self.assertEqual(self.client.get(reverse("order_list"), {"date_basis": "delivery"}).status_code, 200)
        # 營運報表與匯出共用同一個篩選；匯出本來就沒有交車時間欄位。
        from sales.services.order_filters import filter_order_analysis
        filtered = filter_order_analysis(SalesOrder.objects.all(), {"date_basis": "delivery", "date_to": "2099-12-31"})
        self.assertFalse(filtered.filter(pk=order.pk).exists())
