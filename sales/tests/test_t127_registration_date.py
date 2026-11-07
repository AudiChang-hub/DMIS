"""T-127 p6（使用者 2026-11-07 選 B）：領牌日不預設今天；填了實際領牌日（或改日期）就依這一天重算規費，
領牌稅金收入、支出跟著更新。"""
from django.urls import reverse
from django.test import TestCase

from sales.forms import RegistrationStageForm
from sales.models import OrderOperationsProfile, SalesOrder
from sales.tests import test_autosave as autosave


class RegistrationDateTests(TestCase):
    setUp = autosave.OrderAutosaveTests.setUp
    make_order = autosave.OrderAutosaveTests.make_order
    workspace_post = autosave.OrderAutosaveTests.workspace_post

    def save(self, order, day):
        response = self.workspace_post(reverse("registration_save", args=[order.pk]),
                                       {"registration_date": day, "final_plate_number": "abc-1234"})
        self.assertEqual(response.status_code, 200, response.content)
        order.refresh_from_db()
        return order, OrderOperationsProfile.objects.get(order=order)

    def test_registration_date_is_not_prefilled_with_today(self):
        order = self.make_order()
        form = RegistrationStageForm(instance=order)
        self.assertIsNone(form.initial.get("registration_date"))

    def test_changing_registration_date_recalculates_fee_and_tax_rows(self):
        self.model.energy_type = "gas"
        self.model.displacement_cc = 124
        self.model.save(update_fields=["energy_type", "displacement_cc"])
        order = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(plate_insurance_fee=1400)
        order.refresh_from_db()
        order.allocate(self.vehicle)
        self.client.force_login(self.user)
        order, profile = self.save(order, "2026-11-07")
        first = (order.road_maintenance_fee, profile.registration_tax_expense, profile.registration_tax_income)
        order, profile = self.save(order, "2026-10-29")
        second = (order.road_maintenance_fee, profile.registration_tax_expense, profile.registration_tax_income)
        # UAT 7D8EEE（SUI 125、124 c.c. 油車，強制險一年）：號牌 300＋行照 150＋檢驗 200＋公路養管＋牌照稅 0。
        # 11/07 剩 54 個標準日，公路養管 450×54÷360＝67，規費 717；10/29 剩 62 日＝77，規費 727（使用者：727 才正確）。
        self.assertEqual(first, (67, 717, 717))
        self.assertEqual(second, (77, 727, 727))
        order, profile = self.save(order, "2026-11-07")
        self.assertEqual((order.road_maintenance_fee, profile.registration_tax_expense, profile.registration_tax_income), (67, 717, 717))
