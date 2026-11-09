"""T-139（11/09 測試）p5：全部訂單列表的「已結案」一律用同一個樣式；
結案時領牌還沒完成的單另標「領牌未完成」。只改列表，訂單頁照舊。"""
import re

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import PaymentRecord, SalesOrder
from sales.services.payment_summary import payment_summary
from sales.tests import test_order_flow as flow


class ClosedStatusPillTests(TestCase):
    setUp = flow.OrderFlowTests.setUp
    make_order = flow.OrderFlowTests.make_order

    def closed(self, status):
        order = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(status=status, closed_at=timezone.now(), closed_by="測試", submitted_by=self.user)
        return SalesOrder.objects.get(pk=order.pk)

    def status_cell(self, page, order):
        index = page.find(order.number)
        self.assertGreater(index, 0, order.number)
        row = page[page.rfind("<tr", 0, index):page.find("</tr>", index)]
        return re.search(r'<span class="status-pill [^"]+">[^<]*</span>(?:<small[^>]*>[^<]*</small>)*', row).group(0)

    def test_closed_orders_share_one_pill_and_registration_gap_is_labelled(self):
        complete = self.closed(SalesOrder.Status.COMPLETED)
        gap = self.closed(SalesOrder.Status.DELIVERED_DOCS_PENDING)
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_list") + "?tab=closed").content.decode()

        complete_cell, gap_cell = self.status_cell(page, complete), self.status_cell(page, gap)
        self.assertIn('<span class="status-pill status-completed">已結案</span>', complete_cell)
        self.assertIn('<span class="status-pill status-completed">已結案</span>', gap_cell)
        self.assertNotIn("status-delivered_docs_pending", gap_cell)
        self.assertIn('<small class="order-registration-pending">領牌未完成</small>', gap_cell)
        self.assertNotIn("領牌未完成", complete_cell)

    def test_order_detail_pill_is_untouched(self):
        gap = self.closed(SalesOrder.Status.DELIVERED_DOCS_PENDING)
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[gap.pk])).content.decode()
        self.assertIn('status-pill large status-delivered_docs_pending', page)


class UnsettledMarkerTests(TestCase):
    """T-139 p8（使用者 2026-11-09 選 A）：交車後客戶應收未收清，列表狀態欄加紅色「款項未結清 $金額」。
    含車行掛帳；分期撥款、平台撥款不算；交車前與取消的單不顯示。"""
    setUp = flow.OrderFlowTests.setUp
    make_order = flow.OrderFlowTests.make_order

    def order(self, status, **changes):
        order = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(status=status, submitted_by=self.user, **changes)
        return SalesOrder.objects.get(pk=order.pk)

    def pay(self, order, amount, kind=PaymentRecord.ReceiptKind.CUSTOMER, expected=0):
        return PaymentRecord.objects.create(order=order, item_name="測試收款", receipt_kind=kind, expected_amount=expected,
                                            received_amount=amount, received_on=timezone.localdate(),
                                            payment_method="cash" if amount else "", confirmed=bool(amount),
                                            confirmed_by="測試" if amount else "")

    def cell(self, order, tab):
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_list") + f"?tab={tab}").content.decode()
        index = page.find(order.number)
        self.assertGreater(index, 0, order.number)
        return page[page.rfind("<tr", 0, index):page.find("</tr>", index)]

    def test_dealer_credit_after_delivery_is_marked_with_amount(self):
        order = self.order(SalesOrder.Status.COMPLETED, source_type="dealer", source=self.dealer)
        due = payment_summary(order)["customer_due"]
        self.assertGreater(due, 0)
        self.assertIn(f'<small class="order-unsettled">款項未結清 ${due:,.0f}</small>', self.cell(order, "delivered"))
        SalesOrder.objects.filter(pk=order.pk).update(closed_at=timezone.now(), closed_by="測試")
        self.assertIn("款項未結清", self.cell(order, "closed"))

    def test_unpaid_lender_disbursement_is_not_customer_unsettled(self):
        order = self.order(SalesOrder.Status.COMPLETED)
        self.pay(order, payment_summary(order)["customer_due"])
        self.pay(order, 0, kind=PaymentRecord.ReceiptKind.LENDER, expected=50000)
        summary = payment_summary(order)
        self.assertEqual((summary["customer_due"], summary["lender_due"]), (0, 50000))
        self.assertNotIn("款項未結清", self.cell(order, "delivered"))

    def test_not_marked_before_delivery(self):
        order = self.order(SalesOrder.Status.ALLOCATION_PENDING)
        self.assertGreater(payment_summary(order)["customer_due"], 0)
        self.assertNotIn("款項未結清", self.cell(order, "open"))

    def test_not_marked_when_paid_in_full(self):
        order = self.order(SalesOrder.Status.COMPLETED)
        self.pay(order, payment_summary(order)["customer_due"])
        self.assertEqual(payment_summary(order)["customer_due"], 0)
        self.assertNotIn("款項未結清", self.cell(order, "delivered"))

    def test_cancelled_orders_are_not_marked(self):
        order = self.order(SalesOrder.Status.CANCELLED)
        self.assertNotIn("款項未結清", self.cell(order, "cancelled"))
