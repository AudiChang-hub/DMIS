"""欣鈴申請退稅同意書（T-158，使用者 2026-11-13）：SUZUKI 油車且有汰舊，和訂購單、個資同意書一起印；
套表列印也能預覽、批次列印。預覽與列印要能核對補助撥款帳戶，所以帶入帳戶的請求一律 POST 並記查看紀錄。"""
import re
from datetime import date, datetime, timedelta, timezone as dt_timezone
from io import BytesIO
from unittest import mock

from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from pypdf import PdfReader

from sales.models import OrderEvent, OrderOperationsProfile, SalesOrder, VehicleModel
from sales.services import form_print
from sales.services.tax_consent_pdf import needs_tax_consent
from sales.tests import test_order_flow as flow
from sales.tests.test_get_requests_read_only import _written_tables

ACCOUNT = "測試銀行 012-3456789"


def pdf_pages(response):
    return [page.extract_text() or "" for page in PdfReader(BytesIO(b"".join(response.streaming_content))).pages]


PRINT_TIME = re.compile(r"列印時間：\d{4}-\d{2}-\d{2} \d{2}:\d{2}")


def without_print_time(pages):
    """訂購單印出當下的「列印時間」（到分鐘）；兩次列印跨分鐘時會不同，比對內容前先遮掉（T-169）。"""
    return [PRINT_TIME.sub("列印時間：—", text) for text in pages]


def picker_forms(html):
    return re.findall(r'<form class="print-picker".*?</form>', html, flags=re.S)


class TaxConsentBase(TestCase):
    setUp_flow = flow.OrderFlowTests.setUp
    make_order = flow.OrderFlowTests.make_order

    def setUp(self):
        self.setUp_flow()
        self.model.brand = "SUZUKI"
        self.model.model_number = "UQ125DA"
        self.model.save()
        self.client.force_login(self.user)

    def eligible_order(self, account=False):
        order = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(is_trade_in_subsidy=True, order_date=date(2026, 11, 13))
        if account:
            OrderOperationsProfile.objects.update_or_create(
                order=order, defaults={"bank_name": "測試銀行", "remittance_account": "012-3456789"},
            )
        return SalesOrder.objects.get(pk=order.pk)

    def viewed(self, order):
        return OrderEvent.objects.filter(order=order, event_type="payout_account_viewed")


class TaxConsentOrderPrintTests(TaxConsentBase):
    def print_documents(self, order, parts=None, method="get"):
        url = reverse("order_documents_print", args=[order.pk])
        return getattr(self.client, method)(url, {"part": parts} if parts is not None else {})

    def test_only_suzuki_gas_orders_with_trade_in(self):
        order = self.eligible_order()
        self.assertTrue(needs_tax_consent(order))
        order.is_trade_in_subsidy = False
        self.assertFalse(needs_tax_consent(order))
        order.is_trade_in_subsidy = True
        for brand, energy in (("SYM", VehicleModel.EnergyType.GAS), ("SUZUKI", VehicleModel.EnergyType.ELECTRIC),
                              ("eReady", VehicleModel.EnergyType.ELECTRIC)):
            with self.subTest(brand=brand, energy=energy):
                order.vehicle_model.brand = brand
                order.vehicle_model.energy_type = energy
                self.assertFalse(needs_tax_consent(order))

    def test_print_all_link_appends_consent_with_blank_account_and_no_writes(self):
        order = self.eligible_order(account=True)
        self.print_documents(order)  # 第一次列印固定公司資料（T-114 白名單），之後才量測
        with CaptureQueriesContext(connection) as ctx:
            pages = pdf_pages(self.print_documents(order))
        self.assertEqual(_written_tables(ctx.captured_queries), set())
        self.assertEqual(len(pages), 4)  # 訂購單兩聯＋個資同意書＋退稅同意書
        consent = pages[-1]
        for text in ("申請退稅同意書", "王小明", "UQ125DA", "欣鈴車業股份有限公司", "台鈴工業股份有限公司", "A123456789", "115"):
            with self.subTest(text=text):
                self.assertIn(text, consent)
        self.assertNotIn("012-3456789", consent)
        self.assertNotIn("申請退稅同意書", "".join(pages[:-1]))
        self.assertFalse(self.viewed(order).exists())

    def test_post_from_picker_prints_account_and_logs(self):
        order = self.eligible_order(account=True)
        pages = pdf_pages(self.print_documents(order, ["privacy", "tax_consent"], method="post"))
        self.assertEqual(len(pages), 2)
        self.assertIn(ACCOUNT, pages[1])
        self.assertEqual(self.viewed(order).count(), 1)
        self.assertIn("列印退稅同意書", self.viewed(order).get().description)

    def test_blank_account_is_left_for_handwriting_without_log(self):
        order = self.eligible_order()
        consent = pdf_pages(self.print_documents(order, ["tax_consent"], method="post"))[0]
        self.assertIn("銀行/郵局帳號", consent)
        self.assertFalse(self.viewed(order).exists())
        # 只印訂購單時不碰帳戶。
        OrderOperationsProfile.objects.update_or_create(order=order, defaults={"remittance_account": "012-3456789"})
        self.print_documents(order, ["contract_customer"], method="post")
        self.assertFalse(self.viewed(order).exists())

    def test_orders_without_trade_in_print_exactly_as_before(self):
        order = self.make_order()
        self.assertEqual(len(pdf_pages(self.print_documents(order))), 3)
        self.assertEqual(self.print_documents(order, ["tax_consent"], method="post").status_code, 302)

    def test_picked_parts_decide_whether_consent_prints(self):
        order = self.eligible_order()
        only_privacy = pdf_pages(self.print_documents(order, ["privacy"], method="post"))
        self.assertEqual(len(only_privacy), 1)
        self.assertNotIn("申請退稅同意書", only_privacy[0])
        only_consent = pdf_pages(self.print_documents(order, ["tax_consent"], method="post"))
        self.assertEqual(len(only_consent), 1)
        self.assertIn("申請退稅同意書", only_consent[0])

    def test_picker_posts_and_offers_consent_only_when_needed(self):
        order = self.eligible_order()
        html = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        form = picker_forms(html)[0]
        self.assertIn('method="post"', form)
        self.assertIn("csrfmiddlewaretoken", form)
        self.assertIn('value="tax_consent" checked', form)
        self.assertIn(reverse("order_tax_consent_preview", args=[order.pk]), form)
        plain = self.make_order()
        form = picker_forms(self.client.get(reverse("order_detail", args=[plain.pk])).content.decode())[0]
        self.assertNotIn("tax_consent", form)
        self.assertNotIn("退稅同意書", form)

    def test_dealer_and_platform_orders_print_consents_without_signing(self):
        """T-174：車行、網路平台的訂單不請客人簽名，但可以列印個資同意書與（符合條件時）退稅同意書。"""
        order = self.eligible_order()
        for source_type in (SalesOrder.SourceType.DEALER, SalesOrder.SourceType.PLATFORM):
            with self.subTest(source_type=source_type):
                SalesOrder.objects.filter(pk=order.pk).update(source_type=source_type)
                html = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "documents"}).content.decode()
                form = picker_forms(html)[0]
                self.assertEqual(re.findall(r'name="part" value="(\w+)" checked', form), ["privacy", "tax_consent"])
                self.assertNotIn("在行動裝置上簽名", html)
                pages = pdf_pages(self.print_documents(order, ["privacy", "tax_consent"], method="post"))
                self.assertEqual(len(pages), 2)
                self.assertIn("退稅", pages[1])

    def test_existing_parts_on_all_three_pages_print_the_same_as_before(self):
        """勾選面板改用 POST：訂單頁、訂單已成立頁、簽署完成頁的既有勾選與預設值不變，送出結果和 GET 相同。"""
        order = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(submitted_by=self.user)
        pages = {
            "order_detail": reverse("order_detail", args=[order.pk]),
            "order_submitted": reverse("order_submitted", args=[order.pk]),
            "order_sign_done": reverse("order_sign_done", args=[order.pk]),
        }
        expected_defaults = {
            "order_detail": ["contract_store", "contract_customer", "privacy"],
            "order_submitted": ["contract_store", "contract_customer", "privacy"],
            "order_sign_done": ["contract_customer"],
        }
        for name, url in pages.items():
            with self.subTest(page=name):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                form = picker_forms(response.content.decode())[0]
                values = re.findall(r'name="part" value="(\w+)"', form)
                checked = re.findall(r'name="part" value="(\w+)" checked', form)
                self.assertEqual(values, ["contract_store", "contract_customer", "privacy"])
                self.assertEqual(checked, expected_defaults[name])
                via_post = pdf_pages(self.print_documents(order, checked, method="post"))
                via_get = pdf_pages(self.print_documents(order, checked))
                self.assertEqual(without_print_time(via_post), without_print_time(via_get))

    def test_post_and_get_compare_equal_across_a_minute_boundary(self):
        """T-169：兩次列印剛好跨分鐘（22:23:59 → 22:24:00），訂購單「列印時間」不同，比對不能因此失敗。"""
        order = self.make_order()
        parts = ["contract_store", "contract_customer", "privacy"]
        clock = {"now": datetime(2026, 11, 13, 14, 23, 59, tzinfo=dt_timezone.utc)}  # 台北 22:23:59
        with mock.patch("django.utils.timezone.now", side_effect=lambda: clock["now"]):
            via_post = pdf_pages(self.print_documents(order, parts, method="post"))
            clock["now"] += timedelta(seconds=1)
            via_get = pdf_pages(self.print_documents(order, parts))
        self.assertIn("列印時間：2026-11-13 22:23", via_post[0])
        self.assertIn("列印時間：2026-11-13 22:24", via_get[0])
        self.assertEqual(without_print_time(via_post), without_print_time(via_get))


class TaxConsentOrderPreviewTests(TaxConsentBase):
    def preview(self, order, method="post"):
        return getattr(self.client, method)(reverse("order_tax_consent_preview", args=[order.pk]))

    def test_preview_shows_page_and_logs_account_view(self):
        order = self.eligible_order(account=True)
        response = self.preview(order)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data:image/webp;base64,", count=1)
        self.assertContains(response, "已帶入補助撥款帳戶")
        self.assertEqual(response["Cache-Control"], "private, no-store, max-age=0")
        self.assertEqual(self.viewed(order).count(), 1)
        self.assertIn("預覽退稅同意書", self.viewed(order).get().description)

    def test_preview_without_account_writes_nothing(self):
        order = self.eligible_order()
        with CaptureQueriesContext(connection) as ctx:
            response = self.preview(order)
        self.assertContains(response, "補助撥款帳戶還沒填")
        self.assertEqual(_written_tables(ctx.captured_queries), set())

    def test_get_is_not_allowed_and_ineligible_orders_404(self):
        order = self.eligible_order(account=True)
        self.assertEqual(self.preview(order, method="get").status_code, 405)
        self.assertFalse(self.viewed(order).exists())
        self.assertEqual(self.preview(self.make_order()).status_code, 404)


class TaxConsentFormPrintTests(TaxConsentBase):
    def test_print_page_offers_toggle_only_for_applicable_orders(self):
        eligible = self.eligible_order()
        self.make_order()
        response = self.client.get(reverse("form_print"))
        self.assertContains(response, 'data-form="tax_consent"', count=1)
        self.assertContains(response, "欣鈴退稅同意書")
        self.assertContains(response, "不適用（限 SUZUKI 油車有汰舊）", count=1)
        values = form_print.form_values(eligible)
        self.assertIn("tax_consent", form_print.suggested_forms(eligible, values))
        self.assertEqual(form_print.form_warnings(eligible, values)["tax_consent"], ["補助撥款帳戶（留白手寫）"])

    def test_preview_and_pdf_show_account_and_log_each_time(self):
        order = self.eligible_order(account=True)
        job = {"job": [f"{order.pk}:tax_consent", f"{order.pk}:receipt"]}
        preview = self.client.post(reverse("form_print_preview"), job)
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(self.viewed(order).count(), 1)
        self.assertIn("預覽", self.viewed(order).get().description)
        response = self.client.post(reverse("form_print_pdf"), job)
        pages = pdf_pages(response)
        self.assertEqual(len(pages), 2)
        self.assertIn(ACCOUNT, pages[1])
        self.assertEqual(self.viewed(order).count(), 2)

    def test_other_forms_still_preview_without_writes(self):
        order = self.eligible_order(account=True)
        with CaptureQueriesContext(connection) as ctx:
            self.client.post(reverse("form_print_preview"), {"job": [f"{order.pk}:receipt", f"{order.pk}:tax_declaration"]})
        self.assertEqual(_written_tables(ctx.captured_queries), set())

    def test_orders_that_do_not_apply_are_skipped(self):
        plain = self.make_order()
        response = self.client.post(reverse("form_print_pdf"), {"job": [f"{plain.pk}:tax_consent"]})
        self.assertEqual(response.status_code, 302)
