"""T-156（使用者 2026-11-13 簡報）：
第 7 頁「應收已經是0，不需要在填實收金額」：應收 0 時不填實收也能完成交車，且不記一筆 0 元收款；應收大於 0 照舊要足額。"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from sales.models import PaymentRecord, SalesOrder
from sales.services.payment_summary import payment_summary
from sales.tests import test_order_lifecycle as lifecycle
from sales.tests import test_order_steps as steps


class ZeroDueDeliveryTests(TestCase):
    setUp = steps.OrderStepTests.setUp
    make_order = steps.OrderStepTests.make_order
    registered_v2 = steps.OrderStepTests.registered_v2
    delivery_payload = lifecycle.OrderLifecycleTests.delivery_payload

    def settled_order(self):
        """頁面開著時（應收大於 0、尾款欄位已顯示）另一筆收款存檔，應收變 0。"""
        order, _vehicle = self.registered_v2()
        total = payment_summary(order)["customer_expected"]
        PaymentRecord.objects.create(order=order, item_name="其他已收款", expected_amount=0, received_amount=total,
                                     received_on=date(2026, 11, 12), payment_method="匯款", confirmed=True)
        order = SalesOrder.objects.get(pk=order.pk)
        self.assertEqual(payment_summary(order)["delivery_due"], Decimal("0"))
        return order

    def post(self, order, **balance):
        self.client.force_login(self.user)
        payload = {**self.delivery_payload(), **{f"balance-{key}": value for key, value in balance.items()}}
        return self.client.post(reverse("delivery_complete", args=[order.pk]), payload, follow=True)

    def assert_delivered_without_zero_receipt(self, order):
        order.refresh_from_db()
        self.assertTrue(order.is_delivered)
        balance = PaymentRecord.objects.get(order=order, system_key="balance")
        self.assertFalse(balance.confirmed)
        self.assertFalse(balance.received_amount)

    def test_zero_due_completes_without_received_amount(self):
        order = self.settled_order()
        response = self.post(order, received_amount="", received_on="", payment_method="現金")
        self.assertNotContains(response, "請填寫實收金額")
        self.assert_delivered_without_zero_receipt(order)

    def test_zero_due_with_zero_typed_does_not_record_zero_receipt(self):
        order = self.settled_order()
        self.post(order, received_amount="0", received_on="", payment_method="現金")
        self.assert_delivered_without_zero_receipt(order)

    def test_positive_due_still_requires_full_amount(self):
        order, _vehicle = self.registered_v2()
        due = payment_summary(order)["delivery_due"]
        self.assertGreater(due, 0)
        self.assertContains(self.post(order, received_amount=""), "請填寫實收金額")
        self.assertContains(self.post(order, received_amount="0", received_on="2026-11-13", payment_method="現金"), "不得少於應收")
        order.refresh_from_db()
        self.assertFalse(order.is_delivered)
        self.post(order, received_amount=str(due), received_on="2026-11-13", payment_method="現金")
        order.refresh_from_db()
        self.assertTrue(order.is_delivered)
        self.assertTrue(PaymentRecord.objects.get(order=order, system_key="balance").confirmed)

    def test_balance_sheet_has_zero_due_hint(self):
        order, _vehicle = self.registered_v2()
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        self.assertIn("data-balance-hint-zero hidden>目前沒有應收尾款，實收金額不必填", page)


# 第 10 頁「身分證不要必填」（PM 轉使用者決定：方案 A＋證號空白改以姓名＋電話歸戶，汰舊補助維持現狀）。
from django.contrib.auth import get_user_model  # noqa: E402
from django.test import override_settings  # noqa: E402

from sales.forms import OrderEditForm  # noqa: E402
from sales.models import VehicleColor, VehicleModel  # noqa: E402
from sales.tests import test_drafts  # noqa: E402
from sales.tests import test_order_wizard as wizard_tests  # noqa: E402


@override_settings(MEDIA_ROOT=wizard_tests.MEDIA)
class OptionalOwnerIdNumberTests(TestCase):
    setUp = test_drafts.OrderDraftTests.setUp
    image = test_drafts.OrderDraftTests.image
    complete_data = test_drafts.OrderDraftTests.complete_data
    post = wizard_tests.OrderWizardTests.post
    draft = wizard_tests.OrderWizardTests.draft
    walk_to = wizard_tests.OrderWizardTests.walk_to

    def test_blank_id_number_creates_order(self):
        # walk_to 每一步都以空白證號送出，車主步驟會 302 前往下一步（不再被必填擋下）。
        draft = self.walk_to("confirm", owner_id_number="")
        self.assertEqual(draft.data.get("owner_id_number", ""), "")
        self.assertEqual(self.post("confirm", action="submit", draft=draft, owner_id_number="").status_code, 302)
        order = SalesOrder.objects.get()
        self.assertEqual(order.owner_id_number, "")

    def test_owner_step_no_longer_marks_id_number_required(self):
        response = self.client.get(reverse("order_create"))
        page = response.content.decode()
        label = page.split('for="id_owner_id_number"', 1)[1].split("</label>", 1)[0]
        self.assertNotIn("必填", label)
        field = page.split('id="id_owner_id_number"', 1)[0].rsplit("<input", 1)[1]
        self.assertNotIn(" required", field)

    def test_filled_id_number_format_still_checked(self):
        draft = self.walk_to("owner")
        response = self.post("owner", draft=draft, owner_id_number="A123456788")
        self.assertEqual(response.status_code, 200)
        self.assertIn("檢查碼對不上", response.content.decode())

    def test_order_page_autosave_accepts_blank_id_number(self):
        draft = self.walk_to("confirm", owner_id_number="")
        self.post("confirm", action="submit", draft=draft, owner_id_number="")
        order = SalesOrder.objects.get()
        form = OrderEditForm({**self.complete_data(), "owner_id_number": "", "owner_phone": "0912000000"}, instance=order)
        form.is_valid()
        self.assertNotIn("owner_id_number", form.errors)


class CustomerGroupingTests(TestCase):
    """證號空白的訂單以「姓名＋電話」歸戶；有證號照舊以證號歸戶。"""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser("t156-admin", password="test-pass-123")
        self.model = VehicleModel.objects.create(brand="測試牌", name="歸戶車", energy_type=VehicleModel.EnergyType.GAS)
        self.color = VehicleColor.objects.create(vehicle_model=self.model, name="白")
        self.client.force_login(self.user)

    def order(self, name, phone, id_number=""):
        return SalesOrder.objects.create(owner_name=name, owner_phone=phone, owner_id_number=id_number,
                                         vehicle_model=self.model, color=self.color)

    def test_blank_id_orders_group_by_name_and_phone(self):
        a1 = self.order("王小明", "0911000001")
        a2 = self.order("王小明", "0911000001")
        b = self.order("陳小華", "0922000002")
        c = self.order("王小明", "0933000003")  # 同名不同電話＝不同客戶
        d1 = self.order("李大同", "0944000004", "A123456789")
        d2 = self.order("李大同（改名）", "0955000005", "A123456789")  # 有證號照舊以證號歸戶
        customers = list(self.client.get(reverse("customer_list")).context["customers"])
        self.assertEqual(len(customers), 4)
        counts = {customer.pk: customer.order_count for customer in customers}
        self.assertEqual(counts[a2.pk], 2)
        self.assertEqual(counts[b.pk], 1)
        self.assertEqual(counts[c.pk], 1)
        self.assertEqual(counts[d2.pk], 2)
        self.assertEqual(self.client.get(reverse("data_maintenance")).context["customer_count"], 4)
        detail = self.client.get(reverse("customer_detail", args=[a1.pk])).content.decode()
        self.assertIn(a1.number, detail)
        self.assertIn(a2.number, detail)
        self.assertNotIn(b.number, detail)
        self.assertNotIn(c.number, detail)
        detail = self.client.get(reverse("customer_detail", args=[d1.pk])).content.decode()
        self.assertIn(d2.number, detail)
