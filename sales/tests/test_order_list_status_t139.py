"""T-139 p5（11/09 測試）：全部訂單列表的「已結案」一律用同一個樣式；
結案時領牌還沒完成的單另標「領牌未完成」。只改列表，訂單頁照舊。"""
import re

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import SalesOrder
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
