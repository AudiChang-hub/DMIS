"""套表列印：取代 Excel 合併列印的信封、減徵貨物稅聲明書、簽收單。"""
from datetime import date
from decimal import Decimal
from io import BytesIO

from django.test import TestCase
from django.urls import reverse
from pypdf import PdfReader

from sales.models import OrderEvent, OrderOperationsProfile, SalesOrder, VehicleModel
from sales.services import form_print
from sales.services.secret_fields import encrypt_secret
from sales.tests import test_order_lifecycle as lifecycle


def pdf_pages(response):
    content = b"".join(response.streaming_content)
    return PdfReader(BytesIO(content)).pages


class FormPrintServiceTests(TestCase):
    make_order = lifecycle.OrderLifecycleTests.make_order

    def setUp(self):
        lifecycle.OrderLifecycleTests.setUp(self)
        self.order, self.vehicle = self.make_order(dealer=True, deposit=Decimal("5000"))
        self.source.code = "PC"
        self.source.save(update_fields=["code"])
        self.order.refresh_from_db()

    def test_values_follow_word_merge_fields(self):
        self.order.allocated_vehicle = self.vehicle
        self.order.final_plate_number = "PHP-2121"
        self.order.old_owner_same_as_owner = False
        self.order.old_owner_name = "蔡艷媚"
        self.order.old_owner_id_number = "F222969060"
        self.order.trade_in_plate = "MFX-7610"
        self.order.save()
        OrderOperationsProfile.objects.update_or_create(order=self.order, defaults={
            "old_vehicle_engine_number": "SJ25KL-133437",
            "installment_info": "分期和潤  24 期，每期 3,000",
            "customer_service_phone": "02-8953-8686",
        })
        order = SalesOrder.objects.select_related("operations", "source", "allocated_vehicle").get(pk=self.order.pk)

        values = form_print.form_values(order)

        self.assertEqual(values["dealer"], "PC")
        self.assertEqual(values["model_number"], "UQ125DA")
        self.assertEqual(values["identifier"], self.vehicle.engine_number)
        self.assertEqual(values["identifier_label"], "引擎號碼")
        self.assertEqual(values["maker"], "台鈴")
        self.assertEqual(values["old_engine"], "SJ25KL-133437")
        self.assertEqual(values["customer_service_phone"], "客服電話：02-8953-8686")
        self.assertEqual(form_print.default_receipt_note(values), "■收舊車 MFX-7610、行照、鑰匙、稅金。")
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
        self.order.old_owner_name = "蔡艷媚"
        self.order.old_owner_id_number = ""
        self.order.old_owner_phone = ""
        self.order.old_owner_household_address = "台北市"

        values = form_print.form_values(self.order)

        self.assertEqual(values["old_owner_name"], "蔡艷媚")
        self.assertEqual(values["old_owner_id_number"], "A123456789")
        self.assertEqual(values["old_owner_phone"], "0912345678")
        self.assertEqual(values["old_owner_address"], "台北市")

    def test_receipt_insurance_follows_order_period(self):
        self.order.compulsory_insurance_period = SalesOrder.CompulsoryInsurancePeriod.TWO_YEARS

        self.assertEqual(form_print.form_values(self.order)["insurance"], "富邦產物險 2 年")

    def test_roc_date_matches_word_time_field(self):
        self.assertEqual(form_print.roc_chinese_date(date(2026, 10, 14)), "中華民國一一五年十月十四日")
        self.assertEqual(form_print.roc_chinese_date(date(2027, 1, 20)), "中華民國一一六年一月二十日")
        self.assertEqual(form_print.roc_chinese_date(date(2026, 12, 31)), "中華民國一一五年十二月三十一日")

    def test_pdf_groups_same_paper_and_uses_form_sizes(self):
        jobs = [
            form_print.PrintJob(self.order, "receipt", note="■期望送達時間：週一", address="新北市三重區"),
            form_print.PrintJob(self.order, "envelope"),
            form_print.PrintJob(self.order, "tax_declaration"),
        ]

        pages = PdfReader(BytesIO(form_print.build_forms_pdf(jobs, today=date(2026, 10, 14)))).pages

        sizes = [(round(float(page.mediabox.width) / 72 * 25.4), round(float(page.mediabox.height) / 72 * 25.4)) for page in pages]
        self.assertEqual(sizes, [(210, 170), (210, 297), (210, 297)])
        self.assertIn("王小明", pages[0].extract_text())
        self.assertIn("期望送達時間", pages[2].extract_text())


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

    def test_search_narrows_orders(self):
        response = self.client.get(reverse("form_print"), {"q": self.other.number})

        self.assertContains(response, self.other.number)
        self.assertNotContains(response, f'data-number="{self.order.number}"')

    def test_pdf_contains_each_picked_form(self):
        response = self.client.post(reverse("form_print_pdf"), {
            "job": [f"{self.order.pk}:envelope", f"{self.order.pk}:receipt", f"{self.other.pk}:envelope", "bad", f"{self.order.pk}:nope"],
            f"note_{self.order.pk}": "■期望送達時間：週一",
            f"address_{self.order.pk}": "新北市三重區",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(len(pdf_pages(response)), 3)

    def test_nothing_picked_returns_to_page(self):
        response = self.client.post(reverse("form_print_pdf"), {"job": []})

        self.assertRedirects(response, reverse("form_print"), fetch_redirect_response=False)

    def test_deleted_orders_are_skipped(self):
        SalesOrder.objects.filter(pk=self.other.pk).update(deleted_at="2026-10-14T00:00:00+08:00")

        response = self.client.post(reverse("form_print_pdf"), {"job": [f"{self.other.pk}:envelope"]})

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

        response = self.client.post(reverse("form_print_pdf"), {"job": jobs})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Pw-9527", pdf_pages(response)[0].extract_text())
        self.assertTrue(OrderEvent.objects.filter(order=self.order, event_type="secret_viewed", description__contains="套表列印").exists())

    def test_electric_envelope_without_saved_password_prints_phone(self):
        VehicleModel.objects.filter(pk=self.model.pk).update(energy_type=VehicleModel.EnergyType.ELECTRIC)

        response = self.client.post(reverse("form_print_pdf"), {"job": [f"{self.order.pk}:envelope"]})

        self.assertEqual(response.status_code, 200)
        self.assertIn("車控密碼：0912345678", pdf_pages(response)[0].extract_text().replace(" ", ""))

    def test_get_is_not_allowed_for_pdf(self):
        self.assertEqual(self.client.get(reverse("form_print_pdf")).status_code, 405)
