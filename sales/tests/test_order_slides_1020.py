"""1.86.24（使用者 2026-10-20 投影片 T-20～T-22）：建單與訂購單不露出系統算出的牌險金額、
送達地點建單時不必填（交車前提醒）、訂購單不再列舊車主姓名與舊車車牌。"""
import tempfile
import uuid
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from sales.forms import DeliveryCompletionForm
from sales.models import PrintCompany, SalesOrder
from sales.services.document_signing import contract_terms, current_fingerprint
from sales.services.order_contract_pdf import build_order_contract_pdf
from sales.tests import test_completed_order_corrections as correction_tests
from sales.tests import test_order_wizard
from sales.tests.test_order_fixes_1622 import pdf_text

MEDIA = tempfile.mkdtemp()


class ContractSlides1020Tests(TestCase):
    setUpTestData = classmethod(correction_tests.CompletedOrderCorrectionTests.setUpTestData.__func__)
    setUp = correction_tests.CompletedOrderCorrectionTests.setUp
    order = correction_tests.CompletedOrderCorrectionTests.order

    def contract_text(self, **overrides):
        company, _ = PrintCompany.objects.update_or_create(key="home", defaults=dict(
            legal_name="測試機車行", tax_id="12345678", address="測試地址", phone="02-1234"))
        data = dict(source_type="store", source=None, vehicle_price=75000, actual_balance=76396,
                    plate_insurance_fee=1396, registration_plate_fee=740, registration_calculated_total=1396,
                    status=SalesOrder.Status.ALLOCATION_PENDING, registration_date=None, deposit_amount=0,
                    print_company=company, print_company_snapshot={
                        "legal_name": "測試機車行", "tax_id": "12345678", "address": "測試地址", "phone": "02-1234"})
        data.update(overrides)
        order = self.order(**data)
        return order, pdf_text(build_order_contract_pdf(SalesOrder.objects.get(pk=order.pk)))

    def test_system_plate_fee_is_not_printed_or_derivable(self):
        # T-20：留空照系統算的牌險不印金額，應收與尾款也扣掉、註明牌險另計，客人無法相減推算。
        order, text = self.contract_text(plate_insurance_auto=True)
        self.assertEqual(order.customer_balance_due, 76396)
        self.assertNotIn("1,396", text)
        self.assertNotIn("76,396", text)
        self.assertIn("稅金 牌險 1 另計 另計", text)
        self.assertIn("應收 $75,000（牌險另計）", text)
        self.assertIn("預估尾款 $75,000（牌險另計）", text)

    def test_registered_system_plate_fee_hides_rate_details(self):
        _order, text = self.contract_text(plate_insurance_auto=True, registration_date=date(2026, 10, 1))
        self.assertNotIn("1,396", text)
        self.assertNotIn("c.c.", text)
        self.assertIn("牌險另計", text)

    def test_typed_plate_fee_is_printed_as_agreed(self):
        _order, text = self.contract_text(plate_insurance_auto=False, plate_insurance_fee=2500, actual_balance=77500)
        self.assertIn("2,500", text)
        self.assertIn("$77,500", text)
        self.assertNotIn("牌險另計", text)

    def test_contract_drops_old_owner_name_and_plate(self):
        # T-22：訂單階段不會填舊車主與舊車車牌，訂購單不再列；訂單資料與內容指紋的欄位不變。
        order, text = self.contract_text(
            is_trade_in_subsidy=True, old_owner_same_as_owner=False, subsidy_type="汰舊換新",
            old_owner_name="王舊主", trade_in_plate="OLD-1234")
        self.assertIn("汰舊／補助資料", text)
        self.assertIn("不同人", text)
        for hidden in ("舊車主姓名", "舊車車牌", "王舊主", "OLD-1234"):
            self.assertNotIn(hidden, text)
        terms = contract_terms(order)
        self.assertEqual((terms["old_owner_name"], terms["trade_in_plate"]), ("王舊主", "OLD-1234"))
        self.assertEqual(len(current_fingerprint(order, "contract")), 64)

    def test_signed_contract_fingerprint_does_not_depend_on_layout(self):
        order, _text = self.contract_text(plate_insurance_auto=True)
        before = current_fingerprint(order, "contract")
        build_order_contract_pdf(order)
        self.assertEqual(current_fingerprint(order, "contract"), before)


@override_settings(MEDIA_ROOT=MEDIA)
class OrderWizardSlides1020Tests(TestCase):
    setUp = test_order_wizard.OrderWizardTests.setUp
    image = test_order_wizard.OrderWizardTests.image
    complete_data = test_order_wizard.OrderWizardTests.complete_data
    post = test_order_wizard.OrderWizardTests.post
    draft = test_order_wizard.OrderWizardTests.draft

    def login_admin(self):
        admin = get_user_model().objects.create_superuser("admin", password="test-only-123")
        self.client.force_login(admin)
        self.model.displacement_cc = 124
        self.model.save(update_fields=["displacement_cc"])

    def walk(self, last, **changes):
        self.key = str(uuid.uuid4())
        draft = None
        for step in ("vehicle", "owner", "tradein", "delivery", "accessories", "deposit", "confirm"):
            if step == last:
                return draft
            response = self.post(step, draft=draft, **changes)
            self.assertEqual(response.status_code, 302, response.content.decode()[:300])
            draft = self.draft()
        return draft

    def test_plate_section_shows_no_estimate_even_for_finance_staff(self):
        # T-20：建單畫面客人看得到，有財務權限也只顯示牌險費欄位，不列試算明細與金額。
        self.login_admin()
        page = self.client.get(reverse("order_create")).content.decode()
        self.assertIn("<summary>牌險費</summary>", page)
        self.assertIn('<div class="section-title" hidden>', page)
        self.assertIn('<div class="registration-fee-details" hidden>', page)
        self.assertIn('placeholder="留空依系統計算"', page)
        self.assertIn("留空依系統計算；有填金額就照填的收。", page)
        for leaked in ("系統預估", "油車＝規費＋強制險", "牌險手續費收入"):
            self.assertNotIn(leaked, page)
        # 費率明細那一行（排氣量、計費天數、依訂單日預估）只留在隱藏的標題列，畫面不顯示。
        self.assertIn('<p id="registration-rate-summary">', page.split('<div class="section-title" hidden>', 1)[1][:200])

    def test_confirm_step_lists_system_plate_fee_without_amount(self):
        self.login_admin()
        draft = self.walk("confirm", plate_insurance_fee="")
        page = self.client.get(reverse("order_create"), {"draft": draft.pk, "step": "confirm"}).content.decode()
        summary = page.split("wizard-summary", 1)[1].split("</section>", 1)[0]
        self.assertIn("留空，依系統計算", summary)
        self.assertNotIn("系統試算", summary)
        self.post("confirm", action="submit", draft=draft, plate_insurance_fee="")
        order = SalesOrder.objects.get()
        # 計費規則不變：留空仍照系統算進尾款。
        self.assertTrue(order.plate_insurance_auto)
        self.assertGreater(order.plate_insurance_fee, 0)
        self.assertEqual(order.plate_insurance_fee, order.registration_calculated_total)

    def test_delivery_destination_can_be_left_blank(self):
        # T-21：送至指定地點時客人可能還沒決定地點，建單不擋。
        draft = self.walk("accessories", delivery_method="direct_delivery", delivery_destination="")
        self.assertEqual(draft.data.get("delivery_method"), "direct_delivery")
        page = self.client.get(reverse("order_create"), {"draft": draft.pk, "step": "delivery"}).content.decode()
        self.assertIn('id="delivery-destination-field" data-conditional="delivery-destination">', page)
        self.assertNotIn("conditional-required", page)
        self.assertNotIn('byId("id_delivery_destination").required', page)
        self.assertIn("客人還沒決定可先留空，交車前再補上。", page)


class DeliveryDestinationReminderTests(TestCase):
    setUpTestData = classmethod(correction_tests.CompletedOrderCorrectionTests.setUpTestData.__func__)
    order = correction_tests.CompletedOrderCorrectionTests.order

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin", password="test-only-123"))

    def test_order_page_reminds_before_delivery_without_blocking(self):
        order = self.order(status=SalesOrder.Status.DELIVERY_PENDING, delivery_method="direct_delivery",
                           delivery_destination="")
        self.assertTrue(order.delivery_destination_missing)
        page = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "delivery"}).content.decode()
        self.assertIn('id="delivery-destination-reminder"', page)
        self.assertIn("送達地點尚未填寫", page)
        self.assertNotIn("送達地點尚未填寫", "".join(order.delivery_blockers(ignore_balance=True)))
        # 實際交付時仍要填目的地。
        form = DeliveryCompletionForm(order, data={"delivery_method": "direct_delivery", "delivery_destination": ""})
        form.is_valid()
        self.assertIn("delivery_destination", form.errors)

    def test_no_reminder_once_destination_is_filled_or_for_store_pickup(self):
        filled = self.order(status=SalesOrder.Status.DELIVERY_PENDING, delivery_method="carrier",
                            delivery_destination="台中市")
        pickup = self.order(status=SalesOrder.Status.DELIVERY_PENDING, delivery_method="store_pickup")
        for order in (filled, pickup):
            self.assertFalse(order.delivery_destination_missing)
            page = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "delivery"}).content.decode()
            self.assertNotIn('id="delivery-destination-reminder"', page)
