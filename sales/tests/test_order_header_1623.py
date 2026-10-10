"""1.62.3：訂單頁首固定、完成編輯、生日（民國＋西元）與證件號碼不遮罩。"""
from datetime import date

from django.urls import reverse

from sales.templatetags.sales_format import roc_date
from sales.tests.test_completed_order_corrections import CompletedOrderCorrectionTests
from django.test import TestCase, SimpleTestCase


class RocDateTests(SimpleTestCase):
    def test_roc_date(self):
        self.assertEqual(roc_date(date(1992, 1, 21)), "民國 81 年 1 月 21 日")
        self.assertEqual(roc_date(None), "")


class OrderHeaderTests(TestCase):
    setUpTestData = classmethod(CompletedOrderCorrectionTests.setUpTestData.__func__)
    setUp = CompletedOrderCorrectionTests.setUp
    order = CompletedOrderCorrectionTests.order

    def test_detail_shows_phone_birthdays_and_full_id(self):
        order = self.order(owner_birth_date=date(1992, 1, 21))
        response = self.client.get(reverse("order_detail", args=[order.pk]))
        self.assertContains(response, "data-sticky-hero")
        self.assertContains(response, "民國 81 年 1 月 21 日")
        self.assertContains(response, "西元 1992/01/21")
        self.assertContains(response, "1992/01/21")
        self.assertContains(response, "電話 <strong>0912345678</strong>", html=False)
        self.assertContains(response, "A123456789")
        self.assertNotContains(response, "A1＊")

    def test_edit_page_has_finish_button(self):
        order = self.order()
        response = self.client.get(reverse("order_edit", args=[order.pk]))
        self.assertContains(response, "完成編輯")
        self.assertContains(response, "data-workspace-finish")
        self.assertContains(response, f'data-finish-url="{reverse("order_detail", args=[order.pk])}"')
