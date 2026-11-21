"""套表列印：取代 Excel 合併列印的信封、減徵貨物稅聲明書、簽收單。"""
import re
import zipfile
from datetime import date
from decimal import Decimal
from io import BytesIO

from django.test import TestCase
from django.urls import reverse
from pypdf import PdfReader

from sales.models import InstallmentCompany, OrderEvent, OrderOperationsProfile, SalesOrder, VehicleModel
from sales.services import form_print
from sales.services.secret_fields import encrypt_secret
from sales.tests import test_order_lifecycle as lifecycle


def pdf_pages(response):
    content = b"".join(response.streaming_content)
    return PdfReader(BytesIO(content)).pages


def docx_document(content):
    with zipfile.ZipFile(BytesIO(content)) as package:
        return package.read("word/document.xml").decode("utf-8")


def docx_text(document):
    return "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", document))


class FormPrintServiceTests(TestCase):
    make_order = lifecycle.OrderLifecycleTests.make_order

    def setUp(self):
        lifecycle.OrderLifecycleTests.setUp(self)
        self.order, self.vehicle = self.make_order(dealer=True, deposit=Decimal("5000"))
        self.order.refresh_from_db()

    def test_values_follow_word_merge_fields(self):
        self.order.allocated_vehicle = self.vehicle
        self.order.final_plate_number = "TST-0002"
        self.order.old_owner_same_as_owner = False
        self.order.old_owner_name = "林測試"
        self.order.old_owner_id_number = "A123456789"
        self.order.trade_in_plate = "TST-0001"
        self.order.save()
        OrderOperationsProfile.objects.update_or_create(order=self.order, defaults={
            "old_vehicle_engine_number": "TESTENG-000001",
            "installment_info": "分期和潤  24 期，每期 3,000",
            "customer_service_phone": "02-8953-8686",
        })
        order = SalesOrder.objects.select_related("operations", "source", "allocated_vehicle").get(pk=self.order.pk)

        values = form_print.form_values(order)

        self.assertEqual(values["dealer"], self.source.name, "T-238：車行一律印名稱，不印代碼")
        self.assertEqual(values["model_number"], "UQ125DA")
        self.assertEqual(values["identifier"], self.vehicle.engine_number)
        self.assertEqual(values["identifier_label"], "引擎號碼")
        self.assertEqual(values["maker"], "台鈴")
        self.assertEqual(values["old_engine"], "TESTENG-000001")
        self.assertEqual(values["customer_service_phone"], "客服電話：02-8953-8686")
        self.assertEqual(form_print.default_receipt_note(values), "■收舊車 TST-0001、行照、鑰匙、稅金。")
        self.assertIn("tax_declaration", form_print.suggested_forms(order, values))
        self.assertEqual(form_print.form_warnings(order, values)["envelope"], [])

    def test_order_without_trade_in_does_not_suggest_declaration(self):
        values = form_print.form_values(self.order)

        self.assertEqual(form_print.suggested_forms(self.order, values), ["envelope", "receipt"])
        self.assertIn("此單沒有汰舊資料", form_print.form_warnings(self.order, values)["tax_declaration"])

    def test_same_old_owner_uses_buyer_identity(self):
        self.order.old_owner_same_as_owner = True
        values = form_print.form_values(self.order)

        self.assertEqual(values["old_owner_name"], "王小明")
        self.assertEqual(values["old_owner_id_number"], "A123456789")

    def test_blank_old_owner_fields_fall_back_to_buyer(self):
        self.order.old_owner_same_as_owner = False
        self.order.old_owner_name = "林測試"
        self.order.old_owner_id_number = ""
        self.order.old_owner_phone = ""
        self.order.old_owner_household_address = "台北市"

        values = form_print.form_values(self.order)

        self.assertEqual(values["old_owner_name"], "林測試")
        self.assertEqual(values["old_owner_id_number"], "A123456789")
        # 聯絡地址與電話一律印新車主的（使用者 2026-10-22 T-81），舊車主有填也不採用。
        self.assertEqual(values["old_owner_phone"], self.order.owner_phone)
        self.assertEqual(values["old_owner_address"], self.order.owner_address)
        self.order.old_owner_phone = "0922000111"
        values = form_print.form_values(self.order)
        self.assertEqual((values["old_owner_phone"], values["old_owner_address"]), (self.order.owner_phone, self.order.owner_address))

    def test_receipt_insurance_follows_order_period(self):
        self.order.compulsory_insurance_period = SalesOrder.CompulsoryInsurancePeriod.TWO_YEARS

        self.assertEqual(form_print.form_values(self.order)["insurance"], "富邦產物險 2 年")

    def test_roc_date_matches_word_time_field(self):
        self.assertEqual(form_print.roc_chinese_date(date(2026, 10, 14)), "中華民國一一五年十月十四日")
        self.assertEqual(form_print.roc_chinese_date(date(2027, 1, 20)), "中華民國一一六年一月二十日")
        self.assertEqual(form_print.roc_chinese_date(date(2026, 12, 31)), "中華民國一一五年十二月三十一日")

    def test_pdf_groups_a4_forms(self):
        jobs = [
            form_print.PrintJob(self.order, "receipt", note="■期望送達時間：週一", address="新北市三重區"),
            form_print.PrintJob(self.order, "tax_declaration"),
        ]

        pages = PdfReader(BytesIO(form_print.build_forms_pdf(jobs, today=date(2026, 10, 14)))).pages

        sizes = [(round(float(page.mediabox.width) / 72 * 25.4), round(float(page.mediabox.height) / 72 * 25.4)) for page in pages]
        self.assertEqual(sizes, [(210, 297), (210, 297)])
        self.assertIn("王小明", pages[0].extract_text())
        self.assertIn("期望送達時間", pages[1].extract_text())
        with self.assertRaises(ValueError):
            form_print.build_forms_pdf([form_print.PrintJob(self.order, "envelope")])

    def test_envelope_docx_keeps_word_page_setup(self):
        # 2026-10-17：信封紙張固定 21×17 cm 橫向，邊界左 5、右 2 cm；油車上 4、下 2 cm，電車上 3.7、下 1.5 cm。
        electric, _vehicle = self.make_order(deposit=Decimal("5000"))
        electric.vehicle_model = VehicleModel.objects.create(
            brand="SUZUKI", name="e-ADDRESS", model_number="EV076SZV", energy_type=VehicleModel.EnergyType.ELECTRIC,
        )
        SalesOrder.objects.filter(pk=electric.pk).update(vehicle_model=electric.vehicle_model)
        SalesOrder.objects.filter(pk=self.order.pk).update(owner_name="王<小明>")
        orders = list(SalesOrder.objects.select_related("vehicle_model", "source").filter(pk__in=[self.order.pk, electric.pk]).order_by("pk"))

        document = docx_document(form_print.build_envelopes_docx(orders))

        sections = re.findall(r"<w:sectPr>.*?</w:sectPr>", document)
        self.assertEqual(len(sections), 2)
        for section in sections:
            self.assertIn('<w:pgSz w:w="11907" w:h="9639" w:orient="landscape"', section)
            self.assertIn('w:right="1134"', section)
            self.assertIn('w:left="2835"', section)
        self.assertIn('w:top="2268" w:right="1134" w:bottom="1134"', sections[0])
        self.assertIn('w:top="2098" w:right="1134" w:bottom="851"', sections[1])
        text = docx_text(document)
        self.assertIn(f"{self.source.name} 王&lt;小明&gt;", text)  # T-238：車行印名稱
        self.assertIn("車型：UQ125DA", text)
        self.assertIn("車型：EV076SZV", text)
        self.assertIn("車控密碼：0912345678", text)
        self.assertNotIn("{{", document)


class EnvelopeServicePhoneTests(TestCase):
    """T-266：信封客服電話依分期公司帶入；自訂分期沒有主檔，用名稱對到啟用中的分期公司主檔。"""

    make_order = lifecycle.OrderLifecycleTests.make_order

    def setUp(self):
        lifecycle.OrderLifecycleTests.setUp(self)
        self.order, _vehicle = self.make_order(dealer=True, deposit=Decimal("5000"))
        InstallmentCompany.objects.create(name="測試分期甲企業", customer_service_phone="0800-000-111")
        InstallmentCompany.objects.create(name="測試分期乙國際", customer_service_phone="0800-000-222")
        InstallmentCompany.objects.create(name="停用分期", customer_service_phone="0800-000-999", active=False)

    def custom_installment(self, company, phone=""):
        # 自訂分期存檔後沒有分期公司主檔，只留分期公司文字（installment_plan.sync 的自訂分支）。
        SalesOrder.objects.filter(pk=self.order.pk).update(
            payment_type=SalesOrder.PaymentType.INSTALLMENT, installment_custom=True,
            installment_company=company, installment_periods=24, installment_monthly=Decimal("3000"),
            installment_company_master=None,
        )
        OrderOperationsProfile.objects.update_or_create(order=self.order, defaults={"customer_service_phone": phone})
        return form_print.form_values(SalesOrder.objects.get(pk=self.order.pk))["customer_service_phone"]

    def test_custom_company_a_installment_prints_master_phone(self):
        self.assertEqual(self.custom_installment("測試分期甲"), "客服電話：0800-000-111")

    def test_custom_company_b_installment_prints_master_phone(self):
        self.assertEqual(self.custom_installment("測試分期乙"), "客服電話：0800-000-222")

    def test_custom_installment_full_master_name_prints_phone(self):
        self.assertEqual(self.custom_installment("測試分期乙國際股份有限公司"), "客服電話：0800-000-222")

    def test_unmatched_or_inactive_company_stays_blank(self):
        self.assertEqual(self.custom_installment("其他分期"), "")
        self.assertEqual(self.custom_installment("停用分期"), "")
        self.assertEqual(self.custom_installment(""), "")

    def test_operations_phone_wins(self):
        self.assertEqual(self.custom_installment("測試分期甲", phone="02-0000-0000"), "客服電話：02-0000-0000")

    def test_master_without_phone_falls_back_to_name_match(self):
        blank = InstallmentCompany.objects.create(name="測試分期甲分期", customer_service_phone="")
        SalesOrder.objects.filter(pk=self.order.pk).update(
            payment_type=SalesOrder.PaymentType.INSTALLMENT, installment_company="測試分期甲企業",
            installment_company_master=blank,
        )
        OrderOperationsProfile.objects.update_or_create(order=self.order, defaults={"customer_service_phone": ""})
        values = form_print.form_values(SalesOrder.objects.get(pk=self.order.pk))
        self.assertEqual(values["customer_service_phone"], "客服電話：0800-000-111")

    def test_cash_order_has_no_phone(self):
        SalesOrder.objects.filter(pk=self.order.pk).update(
            payment_type=SalesOrder.PaymentType.CASH, installment_company="測試分期甲", installment_company_master=None,
        )
        values = form_print.form_values(SalesOrder.objects.get(pk=self.order.pk))
        self.assertEqual(values["customer_service_phone"], "")


class FormPrintViewTests(TestCase):
    make_order = lifecycle.OrderLifecycleTests.make_order

    def setUp(self):
        lifecycle.OrderLifecycleTests.setUp(self)
        self.order, _vehicle = self.make_order(deposit=Decimal("5000"))
        self.other, _vehicle = self.make_order(dealer=True, deposit=Decimal("5000"))
        self.client.force_login(self.user)

    def test_page_lists_orders_with_form_toggles(self):
        response = self.client.get(reverse("form_print"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.number)
        self.assertContains(response, 'data-form="envelope"', count=2)
        self.assertContains(response, "信封・油車")
        self.assertContains(response, reverse("form_print_pdf"))
        self.assertContains(response, reverse("form_print_envelopes"))

    def test_search_narrows_orders(self):
        response = self.client.get(reverse("form_print"), {"q": self.other.number})

        self.assertContains(response, self.other.number)
        self.assertNotContains(response, f'data-number="{self.order.number}"')

    def test_pdf_contains_picked_a4_forms_only(self):
        response = self.client.post(reverse("form_print_pdf"), {
            "job": [f"{self.order.pk}:envelope", f"{self.order.pk}:receipt", f"{self.other.pk}:envelope", "bad", f"{self.order.pk}:nope"],
            f"note_{self.order.pk}": "■期望送達時間：週一",
            f"address_{self.order.pk}": "新北市三重區",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(len(pdf_pages(response)), 1)

    def test_envelopes_download_as_word_file(self):
        response = self.client.post(reverse("form_print_envelopes"), {
            "job": [f"{self.order.pk}:envelope", f"{self.order.pk}:receipt", f"{self.other.pk}:envelope"],
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertTrue(response["Content-Disposition"].startswith("attachment;"))
        self.assertIn("no-store", response["Cache-Control"])
        document = docx_document(b"".join(response.streaming_content))
        self.assertEqual(document.count("<w:sectPr>"), 2)

    def test_envelopes_without_envelope_returns_to_page(self):
        response = self.client.post(reverse("form_print_envelopes"), {"job": [f"{self.order.pk}:receipt"]})

        self.assertRedirects(response, reverse("form_print"), fetch_redirect_response=False)

    def test_nothing_picked_returns_to_page(self):
        response = self.client.post(reverse("form_print_pdf"), {"job": []})

        self.assertRedirects(response, reverse("form_print"), fetch_redirect_response=False)

    def test_deleted_orders_are_skipped(self):
        SalesOrder.objects.filter(pk=self.other.pk).update(deleted_at="2026-10-14T00:00:00+08:00")

        response = self.client.post(reverse("form_print_envelopes"), {"job": [f"{self.other.pk}:envelope"]})

        self.assertRedirects(response, reverse("form_print"), fetch_redirect_response=False)

    def make_electric_with_password(self):
        VehicleModel.objects.filter(pk=self.model.pk).update(energy_type=VehicleModel.EnergyType.ELECTRIC)
        OrderOperationsProfile.objects.update_or_create(order=self.order, defaults={
            "vehicle_control_account": "bed768", "vehicle_control_password_encrypted": encrypt_secret("Pw-9527"),
        })
        return [f"{self.order.pk}:envelope"]

    def test_electric_envelope_prints_saved_password_without_login_password(self):
        # 2026-10-15 起只有店內人員使用：不再要求輸入本人登入密碼，列印仍留處理紀錄。
        jobs = self.make_electric_with_password()
        page = self.client.get(reverse("form_print"))
        self.assertNotContains(page, "data-secret-panel")

        response = self.client.post(reverse("form_print_envelopes"), {"job": jobs})

        self.assertEqual(response.status_code, 200)
        self.assertIn("車控密碼：Pw-9527", docx_text(docx_document(b"".join(response.streaming_content))))
        self.assertTrue(OrderEvent.objects.filter(order=self.order, event_type="secret_viewed", description__contains="套表列印").exists())

    def test_electric_envelope_without_saved_password_prints_phone(self):
        VehicleModel.objects.filter(pk=self.model.pk).update(energy_type=VehicleModel.EnergyType.ELECTRIC)

        response = self.client.post(reverse("form_print_envelopes"), {"job": [f"{self.order.pk}:envelope"]})

        self.assertEqual(response.status_code, 200)
        self.assertIn("車控密碼：0912345678", docx_text(docx_document(b"".join(response.streaming_content))))
        self.assertFalse(OrderEvent.objects.filter(order=self.order, event_type="secret_viewed").exists())

    def test_get_is_not_allowed_for_pdf(self):
        self.assertEqual(self.client.get(reverse("form_print_pdf")).status_code, 405)
        self.assertEqual(self.client.get(reverse("form_print_envelopes")).status_code, 405)
