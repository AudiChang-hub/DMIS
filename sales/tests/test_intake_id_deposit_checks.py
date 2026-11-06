"""UAT U-05（證號格式與檢查碼）、U-06（訂金不可超過總價）；使用者 2026-11-03 兩項都選方案 A。"""
import re
from decimal import Decimal

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from sales.forms import OrderEditForm
from sales.models import PaymentRecord, SalesOrder
from sales.services.identity_number import owner_id_number_problem, validate_taiwan_id
from sales.tests import test_drafts
from sales.tests import test_order_wizard as wizard_tests


class OwnerIdNumberRuleTests(SimpleTestCase):
    def test_local_checks_format_and_checksum(self):
        self.assertTrue(validate_taiwan_id("A123456789"))
        self.assertEqual(owner_id_number_problem("local", "a123456789"), "")
        self.assertIn("格式不對", owner_id_number_problem("local", "A12345678"))  # G02：9 碼
        self.assertIn("檢查碼對不上", owner_id_number_problem("local", "A123456788"))  # G02：檢查碼錯
        self.assertIn("車主類型", owner_id_number_problem("local", "83739807"))
        self.assertEqual(owner_id_number_problem("local", ""), "")  # 空白交給必填檢查

    def test_company_and_foreign_only_check_shape(self):
        self.assertEqual(owner_id_number_problem("company", "83739807"), "")
        self.assertIn("8 個數字", owner_id_number_problem("company", "8373980"))
        # 外籍可能用居留證或護照：只要 6–20 碼英數。
        for value in ("A800000014", "X1234567", "AB12345"):
            self.assertEqual(owner_id_number_problem("foreign", value), "")
        self.assertIn("6 到 20 碼", owner_id_number_problem("foreign", "A1-23"))
        self.assertIn("6 到 20 碼", owner_id_number_problem("foreign", "A12"))


@override_settings(MEDIA_ROOT=wizard_tests.MEDIA)
class IntakeIdDepositTests(TestCase):
    setUp = test_drafts.OrderDraftTests.setUp
    image = test_drafts.OrderDraftTests.image
    complete_data = test_drafts.OrderDraftTests.complete_data
    post = wizard_tests.OrderWizardTests.post
    draft = wizard_tests.OrderWizardTests.draft
    walk_to = wizard_tests.OrderWizardTests.walk_to

    def test_g02_bad_id_number_stops_at_owner_step_next_to_field(self):
        draft = self.walk_to("owner")
        for value, words in (("A12345678", "格式不對"), ("A123456788", "檢查碼對不上")):
            response = self.post("owner", draft=draft, owner_id_number=value)
            self.assertEqual(response.status_code, 200)
            page = response.content.decode()
            self.assertIn('data-wizard-panel="owner"', page)
            self.assertNotIn('data-wizard-panel="owner" hidden', page)
            field = page.split('id="id_owner_id_number"', 1)[1].split("</div>", 1)[0]
            self.assertIn(words, field)
        self.assertEqual(self.post("owner", draft=self.draft(), owner_id_number="A123456789").status_code, 302)

    def test_company_and_foreign_pass_with_their_own_shapes(self):
        draft = self.walk_to("owner")
        self.assertEqual(self.post("owner", draft=draft, owner_type="company", owner_id_number="83739807").status_code, 302)
        response = self.post("owner", draft=self.draft(), owner_type="foreign", owner_id_number="AB12345")
        self.assertEqual(response.status_code, 302)

    def test_existing_order_keeps_old_id_number_without_blocking(self):
        draft = self.walk_to("confirm")
        self.assertEqual(self.post("confirm", action="submit", draft=draft).status_code, 302)
        order = SalesOrder.objects.get()
        SalesOrder.objects.filter(pk=order.pk).update(owner_id_number="A123456788")
        order.refresh_from_db()
        data = {**self.complete_data(), "owner_id_number": "A123456788", "owner_phone": "0912000000"}
        form = OrderEditForm(data, instance=order)
        form.is_valid()
        self.assertNotIn("owner_id_number", form.errors)
        changed = OrderEditForm({**data, "owner_id_number": "B123456788"}, instance=order)
        changed.is_valid()
        self.assertIn("檢查碼對不上", " ".join(changed.errors["owner_id_number"]))

    def test_g13_deposit_above_total_is_blocked_next_to_field(self):
        draft = self.walk_to("deposit")
        response = self.post("deposit", draft=draft, deposit_amount="800000", deposit_method="cash")
        self.assertEqual(response.status_code, 200)
        page = response.content.decode()
        self.assertNotIn('data-wizard-panel="deposit" hidden', page)
        field = page.split('id="id_deposit_amount"', 1)[1].split("</div>", 1)[0]
        match = re.search(r"訂金 800,000 元比這張單的總價 ([\d,]+) 元還多", field)
        self.assertIsNotNone(match, field)
        total = match.group(1).replace(",", "")
        over = self.post("deposit", draft=self.draft(), deposit_amount=str(int(total) + 1), deposit_method="cash")
        self.assertEqual(over.status_code, 200)
        # 等於總價可以通過；送出後照常直接入帳。
        self.assertEqual(self.post("deposit", draft=self.draft(), deposit_amount=total, deposit_method="cash").status_code, 302)
        submitted = self.post("confirm", action="submit", draft=self.draft(), deposit_amount=total, deposit_method="cash")
        self.assertEqual(submitted.status_code, 302)
        payment = PaymentRecord.objects.get(order__owner_name=self.complete_data()["owner_name"], system_key="deposit")
        self.assertEqual(payment.received_amount, Decimal(total))

    def test_auto_plate_message_does_not_reveal_total(self):
        draft = self.walk_to("deposit", plate_insurance_fee="")
        response = self.post("deposit", draft=draft, plate_insurance_fee="", deposit_amount="800000", deposit_method="cash")
        self.assertEqual(response.status_code, 200)
        field = response.content.decode().split('id="id_deposit_amount"', 1)[1].split("</div>", 1)[0]
        self.assertIn("訂金比這張單的總價還多", field)
        self.assertNotIn("元比這張單的總價", field)

    def test_page_has_live_hints(self):
        page = self.client.get(reverse("order_create")).content.decode()
        self.assertIn("function ownerIdProblem", page)
        self.assertIn("ownerIdNumber.setCustomValidity(problem)", page)
        self.assertIn("data-deposit-over-hint", page)
