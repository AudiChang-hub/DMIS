"""1.86.37（使用者 2026-10-21 T-49）：分期公司選「其他／自訂分期」時，不顯示「期數與每期金額」選單。

隱藏與清空在前端（見 tests/frontend/order-installment-picker.test.cjs）；這裡確認建單頁與訂單頁共用同一個
可隱藏的選單外框，且選單沒有 name，不會隨表單送出，既有自訂分期的期數與每期金額照原值保存。
"""
import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.forms import OrderEditForm
from sales.models import SalesOrder
from sales.tests import test_completed_order_corrections as correction_tests
from sales.tests import test_order_wizard
from sales.tests.test_order_workspace import form_data

PERIOD_FIELD = re.compile(r'<div class="field" id="installment-period-field"><label for="installment-period-choice">'
                          r'期數與每期金額</label><select id="installment-period-choice">')


def period_select(page):
    return page.split('<select id="installment-period-choice"', 1)[1].split(">", 1)[0]


class OrderCreatePeriodFieldTests(TestCase):
    setUp = test_order_wizard.OrderWizardTests.setUp

    def test_create_page_wraps_period_choice_in_hideable_field(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin", password="test-only-123"))
        page = self.client.get(reverse("order_create")).content.decode()
        self.assertRegex(page, PERIOD_FIELD)
        self.assertNotIn("name=", period_select(page))


class OrderPagePeriodFieldTests(TestCase):
    setUpTestData = classmethod(correction_tests.CompletedOrderCorrectionTests.setUpTestData.__func__)
    order = correction_tests.CompletedOrderCorrectionTests.order

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin", password="test-only-123"))

    def test_custom_order_keeps_its_periods_and_monthly(self):
        order = self.order(status=SalesOrder.Status.ALLOCATION_PENDING, payment_type="installment",
                           installment_custom=True, installment_company="和潤", installment_periods=24,
                           installment_monthly=1250, installment_opening_fee=0)
        page = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "order"}).content.decode()
        self.assertRegex(page, PERIOD_FIELD)
        self.assertNotIn("name=", period_select(page))
        form = OrderEditForm(data=form_data(OrderEditForm(instance=order)), instance=SalesOrder.objects.get(pk=order.pk))
        self.assertTrue(form.is_valid(), form.errors)
        cleaned = form.cleaned_data
        self.assertEqual((cleaned["installment_custom"], cleaned["installment_company"], cleaned["installment_periods"],
                          cleaned["installment_monthly"]), (True, "和潤", 24, 1250))
