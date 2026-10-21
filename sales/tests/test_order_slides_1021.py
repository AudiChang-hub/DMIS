"""1.86.32（使用者 2026-10-21 投影片 T-34、T-38）。

T-34：自訂分期每期金額＝分期價格÷期數（四捨五入，前端，見 tests/frontend/order-installment-picker.test.cjs）。
T-38（使用者選 B）：訂單頁的牌險只有一層、直接展開，只顯示系統試算合計與牌險費；
自行調整、調整原因、明細與強制險期間都不顯示（期間在隱藏區照原值送出，既有試算合計不變）。
"""
import re

from django.test import TestCase
from django.urls import reverse

from sales.forms import OrderEditForm, SalesOrderForm
from sales.models import SalesOrder
from sales.tests import test_order_lifecycle as lifecycle
from sales.tests.test_order_workspace import form_data


class OrderPageRegistrationCardTests(TestCase):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def page(self):
        order, _vehicle = self.make_order()
        self.client.force_login(self.user)
        return self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "order"}).content.decode()

    def test_registration_card_is_one_open_layer_with_two_fields(self):
        page = self.page()
        card = page.split('<details class="card registration-fee-card"', 1)[1].split("</details>", 1)[0]
        opening = card.split(">", 1)[0]
        self.assertIn("open", opening)
        self.assertIn("<summary>領牌規費與強制險</summary>", card)
        self.assertNotIn("店內財務", page)
        self.assertNotIn("registration-fee-subsection", card)
        hidden, visible = card.split('<div class="form-grid registration-fee-card__fields">', 1)
        for name in ("registration_plate_fee", "registration_license_fee", "registration_inspection_fee",
                     "road_maintenance_fee", "license_tax_fee", "compulsory_insurance_fee"):
            self.assertIn(f'name="{name}"', hidden.split("<div hidden>", 1)[1])
            self.assertNotIn(f'name="{name}"', visible)
        self.assertIn('name="compulsory_insurance_period"', hidden.split("<div hidden>", 1)[1])
        self.assertNotIn('name="compulsory_insurance_period"', visible)
        self.assertNotIn("強制險期間", visible)
        for name in ("registration_calculated_total", "plate_insurance_fee"):
            self.assertIn(f'name="{name}"', visible)
        self.assertRegex(visible, r'name="registration_calculated_total"[^>]*readonly')
        for gone in ("registration_manual", "registration_adjustment_reason", "自行調整牌險明細", "牌險調整原因"):
            self.assertNotIn(gone, page)

    def test_manual_detail_and_reason_are_not_form_fields(self):
        for form_class in (SalesOrderForm, OrderEditForm):
            self.assertNotIn("registration_manual", form_class.base_fields)
            self.assertNotIn("registration_adjustment_reason", form_class.base_fields)

    def test_custom_installment_monthly_follows_installment_price(self):
        page = self.page()
        self.assertIn("function installmentPrice()", page)
        self.assertIn("installmentPrice,", page)
        self.assertRegex(page, re.escape("installmentPicker.syncCustomMonthly();"))

    def recalculated(self, order):
        form = OrderEditForm(data=form_data(OrderEditForm(instance=order)), instance=SalesOrder.objects.get(pk=order.pk))
        self.assertTrue(form.is_valid(), form.errors)
        return form.cleaned_data

    def test_existing_insurance_period_and_total_are_unchanged(self):
        # 既有訂單的強制險期間照原值送出（正式站 0 張兩年），試算合計不變；新單預設一年。
        one_year, _vehicle = self.make_order()
        before = self.recalculated(one_year)
        self.assertEqual((before["compulsory_insurance_period"], before["compulsory_insurance_fee"]), (1, 658))
        two_year, _vehicle = self.make_order()
        SalesOrder.objects.filter(pk=two_year.pk).update(compulsory_insurance_period=2)
        two_year.refresh_from_db()
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[two_year.pk]), {"tab": "order"}).content.decode()
        self.assertRegex(page, r'<option value="2" selected>')
        cleaned = self.recalculated(two_year)
        self.assertEqual((cleaned["compulsory_insurance_period"], cleaned["compulsory_insurance_fee"]), (2, 1200))
        self.assertEqual(cleaned["registration_calculated_total"] - before["registration_calculated_total"], 1200 - 658)
        self.assertEqual(SalesOrder._meta.get_field("compulsory_insurance_period").default, 1)
