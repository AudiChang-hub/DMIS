"""T-195（使用者 2026-11-16）：分期單（本店、車行都算）牌險費預設 0，不向客人收。
牌險由本店吸收：照列規費與強制險支出，收入記 0；客人或車行確實要付時，人員自己填正數，收入就等於支出。
現金單不變：留空就照系統試算。"""
import tempfile
import uuid

from django.test import TestCase, override_settings
from django.urls import reverse

from sales.forms import SalesOrderForm
from sales.models import OrderOperationsProfile, SalesOrder
from sales.tests import test_order_wizard
from sales.tests.test_order_workspace import form_data

MEDIA = tempfile.mkdtemp()

INSTALLMENT = dict(
    payment_type="installment", installment_company="和潤", installment_periods="24",
    installment_monthly="3500", installment_opening_fee="0",
)


@override_settings(MEDIA_ROOT=MEDIA)
class InstallmentPlateDefaultTests(TestCase):
    def setUp(self):
        test_order_wizard.OrderWizardTests.setUp(self)
        # 油車要有排氣量，系統才算得出規費與強制險。
        self.model.displacement_cc = 124
        self.model.save(update_fields=["displacement_cc"])

    image = test_order_wizard.OrderWizardTests.image
    complete_data = test_order_wizard.OrderWizardTests.complete_data
    post = test_order_wizard.OrderWizardTests.post
    draft = test_order_wizard.OrderWizardTests.draft
    walk_to = test_order_wizard.OrderWizardTests.walk_to

    def create(self, **changes):
        self.key = str(uuid.uuid4())
        draft = self.walk_to("confirm", **changes)
        response = self.post("confirm", action="submit", draft=draft, **changes)
        self.assertEqual(response.status_code, 302, response.content.decode()[:500])
        order = SalesOrder.objects.get()
        return order, OrderOperationsProfile.objects.get(order=order)

    def assert_store_absorbs(self, order, profile):
        self.assertFalse(order.plate_insurance_auto)
        self.assertEqual(order.plate_insurance_fee, 0)
        self.assertGreater(order.registration_calculated_total, 0)
        # 本店吸收：支出照試算列，收入 0、牌險手續費 0。
        self.assertGreater(profile.registration_tax_expense, 0)
        self.assertGreater(profile.compulsory_insurance_expense, 0)
        self.assertEqual(
            (profile.registration_tax_income, profile.compulsory_insurance_income, profile.agency_fee_income),
            (0, 0, 0),
        )

    def test_installment_blank_plate_fee_defaults_to_zero_store_absorbs(self):
        order, profile = self.create(plate_insurance_fee="", **INSTALLMENT)
        self.assertEqual(order.payment_type, SalesOrder.PaymentType.INSTALLMENT)
        self.assert_store_absorbs(order, profile)

    def test_installment_contract_no_longer_says_plate_charged_separately(self):
        from sales.models import PrintCompany
        from sales.services.order_contract_pdf import build_order_contract_pdf
        from sales.tests.test_order_fixes_1622 import pdf_text

        PrintCompany.objects.update_or_create(key="home", defaults=dict(
            legal_name="測試機車行", tax_id="12345678", address="測試地址", phone="02-1234"))
        order, _profile = self.create(plate_insurance_fee="", **INSTALLMENT)
        text = pdf_text(build_order_contract_pdf(SalesOrder.objects.get(pk=order.pk)))
        self.assertNotIn("另計", text)
        self.assertIn("分期外應收", text)
        # 使用者 2026-11-16：分期單牌險列印「—」；不會印出的舊說明「由融資支付」已刪除，輸出不變。
        self.assertIn("稅金 牌險 1 — —", text)
        self.assertNotIn("融資", text)

    def test_dealer_installment_blank_plate_fee_also_defaults_to_zero(self):
        from sales.models import SalesSource

        dealer = SalesSource.objects.create(name="T195 車行", source_type="dealer")
        order, profile = self.create(plate_insurance_fee="", source_type="dealer", source=str(dealer.pk), **INSTALLMENT)
        self.assertEqual(order.source_type, SalesOrder.SourceType.DEALER)
        self.assert_store_absorbs(order, profile)

    def test_installment_typed_plate_fee_is_charged_and_income_equals_expense(self):
        order, profile = self.create(plate_insurance_fee="1500", **INSTALLMENT)
        self.assertFalse(order.plate_insurance_auto)
        self.assertEqual(order.plate_insurance_fee, 1500)
        self.assertEqual(profile.registration_tax_income, profile.registration_tax_expense)
        self.assertEqual(profile.compulsory_insurance_income, profile.compulsory_insurance_expense)

    def test_cash_blank_plate_fee_still_follows_system_estimate(self):
        order, profile = self.create(plate_insurance_fee="")
        self.assertEqual(order.payment_type, SalesOrder.PaymentType.CASH)
        self.assertTrue(order.plate_insurance_auto)
        self.assertGreater(order.plate_insurance_fee, 0)
        self.assertEqual(order.plate_insurance_fee, order.registration_calculated_total)
        self.assertEqual(profile.registration_tax_income, profile.registration_tax_expense)
        self.assertEqual(profile.compulsory_insurance_income, profile.compulsory_insurance_expense)

    def test_confirm_step_does_not_say_system_calculated_for_installment(self):
        from django.contrib.auth import get_user_model

        # 有財務權限才會在確認頁列出牌險費。
        self.client.force_login(get_user_model().objects.create_superuser("t195-admin", password="test-only-123"))
        self.key = str(uuid.uuid4())
        draft = self.walk_to("confirm", plate_insurance_fee="", **INSTALLMENT)
        page = self.client.get(reverse("order_create"), {"draft": draft.pk, "step": "confirm"}).content.decode()
        summary = page.split("wizard-summary", 1)[1].split("</section>", 1)[0]
        self.assertIn("<dt>付款方式</dt><dd>分期</dd>", summary)
        # 分期單留空＝不收，和填 0 一樣不列牌險費，也不寫「依系統計算」（改版前會寫）。
        self.assertNotIn("留空，依系統計算", summary)

    def test_existing_system_estimated_installment_order_is_not_changed_by_editing(self):
        # 既有照試算的分期單（例如正式站 SO20261112-14527F）存檔時不悄悄改成 0，資料修正另外決定。
        order, _profile = self.create(plate_insurance_fee="", **INSTALLMENT)
        SalesOrder.objects.filter(pk=order.pk).update(plate_insurance_auto=True, plate_insurance_fee=order.registration_calculated_total)
        order.refresh_from_db()
        data = form_data(SalesOrderForm(instance=order))
        self.assertEqual(data["plate_insurance_fee"], "")
        form = SalesOrderForm(data=data, instance=order)
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save(commit=False)
        self.assertTrue(saved.plate_insurance_auto)
        self.assertEqual(saved.plate_insurance_fee, saved.registration_calculated_total)

    def test_switching_existing_cash_order_to_installment_with_blank_fee_defaults_to_zero(self):
        order, _profile = self.create(plate_insurance_fee="")
        self.assertTrue(order.plate_insurance_auto)
        data = form_data(SalesOrderForm(instance=order))
        data.pop("payment_splits", None)
        data.update(plate_insurance_fee="", **INSTALLMENT)
        form = SalesOrderForm(data=data, instance=order)
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save(commit=False)
        self.assertEqual(saved.payment_type, SalesOrder.PaymentType.INSTALLMENT)
        self.assertFalse(saved.plate_insurance_auto)
        self.assertEqual(saved.plate_insurance_fee, 0)
