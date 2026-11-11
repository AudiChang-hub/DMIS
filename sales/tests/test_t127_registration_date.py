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


class RegistrationDateKeptTests(TestCase):
    """使用者選的實際領牌日一定存下來（UAT 7D8EEE、0A6C66）：完成領牌後仍是 10/29、規費 727；
    之後訂單表單自動儲存送出的隱藏舊領牌日不會把它蓋回去。"""
    setUp = autosave.OrderAutosaveTests.setUp
    make_order = autosave.OrderAutosaveTests.make_order
    workspace_post = autosave.OrderAutosaveTests.workspace_post

    def gas_order(self):
        self.model.energy_type = "gas"
        self.model.displacement_cc = 124
        self.model.save(update_fields=["energy_type", "displacement_cc"])
        order = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(plate_insurance_fee=1400)
        order.refresh_from_db()
        order.allocate(self.vehicle)
        self.client.force_login(self.user)
        return order

    def test_chosen_date_survives_completion_by_document_upload(self):
        from sales.models import RegistrationDocument
        from sales.tests.test_order_flow import uploaded_test_pdf
        order = self.gas_order()
        response = self.workspace_post(reverse("registration_save", args=[order.pk]),
                                       {"registration_date": "2026-10-29", "final_plate_number": "php-9836"})
        self.assertEqual(response.status_code, 200, response.content)
        for index, document_type in enumerate((RegistrationDocument.DocumentType.NEW_LICENSE,
                                               RegistrationDocument.DocumentType.REGISTRATION_APPLICATION)):
            self.client.post(reverse("registration_document_upload", args=[order.pk]), {
                "document_type": document_type, "name": "", "file": uploaded_test_pdf(f"doc-{index}.pdf")})
        # 日期與車牌填好就自動完成（T-147）；文件上傳不影響，完成時保留選的日期與依日期算的規費。
        order.refresh_from_db()
        order.refresh_from_db()
        profile = OrderOperationsProfile.objects.get(order=order)
        self.assertTrue(order.is_registration_complete)
        self.assertEqual(str(order.registration_date), "2026-10-29")
        self.assertEqual((order.road_maintenance_fee, profile.registration_tax_expense, profile.registration_tax_income), (77, 727, 727))

    def test_order_form_autosave_does_not_revert_registration_date(self):
        from sales.forms import SalesOrderForm
        from sales.tests.test_order_workspace import form_data
        order = self.gas_order()
        stale = form_data(SalesOrderForm(instance=SalesOrder.objects.get(pk=order.pk)))  # 頁面載入時（還沒有領牌日）
        self.workspace_post(reverse("registration_save", args=[order.pk]),
                            {"registration_date": "2026-10-29", "final_plate_number": "php-9836"})
        form = SalesOrderForm(data={**stale, "registration_date": ""}, instance=SalesOrder.objects.get(pk=order.pk))
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(str(saved.registration_date), "2026-10-29")
        self.assertEqual(saved.road_maintenance_fee, 77)


class ManualTaxOverrideTests(TestCase):
    """改領牌日時人工改過的領牌稅金保留不動（使用者 2026-11-11 T-147，取代 11-07 選 A 的「覆蓋人工金額」）。"""
    setUp = autosave.OrderAutosaveTests.setUp
    make_order = autosave.OrderAutosaveTests.make_order
    workspace_post = autosave.OrderAutosaveTests.workspace_post
    gas_order = RegistrationDateKeptTests.gas_order

    def save(self, order, day, plate="php-9836"):
        response = self.workspace_post(reverse("registration_save", args=[order.pk]),
                                       {"registration_date": day, "final_plate_number": plate})
        self.assertEqual(response.status_code, 200, response.content)
        return OrderOperationsProfile.objects.get(order=order)

    def manual(self, order, amount):
        OrderOperationsProfile.objects.filter(order=order).update(
            registration_tax_expense=amount, registration_tax_income=amount,
            manual_financial_fields=["registration_tax_expense", "registration_tax_income", "vehicle_cost"])

    def test_changed_date_keeps_manual_tax(self):
        from sales.models import OrderChange
        order = self.gas_order()
        self.save(order, "2026-11-07")
        self.manual(order, 999)
        profile = self.save(order, "2026-10-29")
        self.assertEqual((profile.registration_tax_expense, profile.registration_tax_income), (999, 999))
        self.assertIn("registration_tax_expense", profile.manual_financial_fields)
        self.assertFalse(OrderChange.objects.filter(order=order, reason__startswith="領牌日變更").exists())
        self.assertTrue(OrderChange.objects.filter(order=order, changes__has_key="實際領牌日期").exists())

    def test_same_date_keeps_manual_tax(self):
        order = self.gas_order()
        self.save(order, "2026-11-07")
        self.manual(order, 999)
        profile = self.save(order, "2026-11-07", plate="php-9837")
        self.assertEqual((profile.registration_tax_expense, profile.registration_tax_income), (999, 999))
        self.assertIn("registration_tax_expense", profile.manual_financial_fields)
