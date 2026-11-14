"""訂單頁自動儲存三層防護（T-130，使用者 2026-11-07 同意試做）。

起因：7D8EEE 這張單，使用者以為選了領牌日 10/29，但系統先存了預設的今天；接著上傳文件時自動完成領牌，日期就被鎖住。
1. 重要欄位不預填：交車時間、交車收尾款日期、訂金日期、退款／例外結案日期與沒收金額、溢收退款日期留空。
2. 存檔狀態看得見：頁首一個存檔狀態、失敗才顯示紅色提示列（前端 order-workspace.js）。
3. 鎖定前先確認：文件傳齊或資料填齊不再自動完成領牌，頁面跳出確認卡列出實際存下的值，按「確認完成」才鎖定；
   訂金已收妥、收款已確認、交車也改用確認卡（lock-confirm.js）。
"""
import shutil
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from sales.forms import (
    DeliveryCompletionForm,
    DepositStepForm,
    ExceptionCloseForm,
    OverpaymentRefundForm,
    PaymentRecordForm,
    RefundCompletionForm,
)
from sales.models import (
    OrderEvent,
    PaymentRecord,
    RegistrationDocument,
    SalesOrder,
    Store,
    VehicleColor,
    VehicleInventory,
    VehicleModel,
    VehicleSettlementCostRule,
)
from sales.services.deposit_step import save_deposit_step
from sales.services.order_steps import order_step_url
from sales.tests.test_inplace_uploads import png

Doc = RegistrationDocument.DocumentType
STATIC = Path(settings.BASE_DIR) / "static"


class LockConfirmRegistrationTests(TestCase):
    """第 3 層：領牌條件齊全只跳確認卡，不自動鎖定。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media = tempfile.mkdtemp()
        cls.media_override = override_settings(MEDIA_ROOT=cls.media)
        cls.media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls.media_override.disable()
        shutil.rmtree(cls.media, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        from sales.services.print_company import initialize_company

        self.user = get_user_model().objects.create_superuser("t130", "", "test-pass-123")
        self.client.force_login(self.user)
        store = Store.objects.create(name="總店", code="HQ")
        model = VehicleModel.objects.create(brand="SUZUKI", name="SUI 125", energy_type=VehicleModel.EnergyType.GAS)
        color = VehicleColor.objects.create(vehicle_model=model, name="灰")
        VehicleSettlementCostRule.objects.create(vehicle_model=model, amount=Decimal("60000"), effective_from=date(2026, 1, 1))
        self.order = SalesOrder(
            owner_name="王小明", owner_phone="0912345678", owner_address="新北市汐止區", owner_id_number="A123456789",
            vehicle_model=model, color=color, vehicle_price=Decimal("75000"), deposit_amount=Decimal("5000"),
            actual_balance=Decimal("70000"), id_verified=True, status=SalesOrder.Status.ALLOCATION_PENDING,
        )
        initialize_company(self.order, self.user)
        self.order.save()
        vehicle = VehicleInventory.objects.create(
            vehicle_model=model, color=color, engine_number="ENG-T130", ownership_store=store, location_store=store,
        )
        self.order.allocate(vehicle)
        self.order.registration_date = date(2026, 10, 29)
        self.order.final_plate_number = "ABC-1234"
        self.order.save(update_fields=["registration_date", "final_plate_number", "updated_at"])

    def upload(self, document_type, **headers):
        return self.client.post(
            reverse("registration_document_upload", args=[self.order.pk]),
            {"document_type": document_type, "file": png()}, **headers,
        )

    def test_upload_never_completes_registration(self):
        self.assertNotIn("confirm=", self.upload(Doc.NEW_LICENSE)["Location"])
        response = self.upload(Doc.REGISTRATION_APPLICATION)
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_registration_complete, "文件傳齊不可自動完成領牌（7D8EEE）")
        self.assertFalse(OrderEvent.objects.filter(order=self.order, event_type="registration_completed").exists())
        # 文件選填、上傳不跳卡（T-145）；按「確認完成」才跳確認卡並完成（T-172 A′，不自動跳出）。
        self.assertNotIn("confirm=", response["Location"])
        page = self.client.get(order_step_url(self.order.pk, "registration")).content.decode()
        self.assertNotIn("data-lock-auto", page)
        self.assertIn('data-lock-confirm="確認領牌完成"', page)
        self.assertIn(">確認完成</button>", page)
        self.client.post(reverse("registration_complete", args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_registration_complete)

    def test_async_upload_never_returns_confirm_url(self):
        self.upload(Doc.NEW_LICENSE)
        payload = self.upload(Doc.REGISTRATION_APPLICATION, HTTP_X_REQUESTED_WITH="XMLHttpRequest").json()
        self.assertTrue(payload["ok"])
        self.assertNotIn("confirm=", payload["redirect_url"])
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_registration_complete)

    def test_autosave_with_complete_data_waits_for_confirm(self):
        self.order.final_plate_number = ""
        self.order.save(update_fields=["final_plate_number", "updated_at"])
        self.upload(Doc.NEW_LICENSE)
        self.upload(Doc.REGISTRATION_APPLICATION)
        url = reverse("registration_save", args=[self.order.pk])
        data = {"registration_date": "2026-10-29", "final_plate_number": "abc-1234"}
        first = self.client.post(url, data, HTTP_X_ORDER_WORKSPACE="1").json()
        self.assertFalse(first["reload"])
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_registration_complete, "存檔不自動完成，按確認完成才完成（T-172 A′）")
        self.client.post(reverse("registration_complete", args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_registration_complete)
        again = self.client.post(url, {**data, "final_plate_number": "abc-1235"}, HTTP_X_ORDER_WORKSPACE="1").json()
        self.assertFalse(again["reload"])
        self.order.refresh_from_db()
        self.assertEqual(self.order.final_plate_number, "ABC-1235", "完成後仍可修改")

    def test_missing_cost_rule_warning_follows_registration_date_not_county(self):
        # 使用者 2026-11-07 選 A：填了領牌日就檢查成本規則；以前要有縣市才出現，新單沒有縣市所以從不出現。
        warning = '<div class="message warning">目前找不到符合此車型與領牌日期的成本規則，補建前無法完成領牌。</div>'
        page = self.client.get(order_step_url(self.order.pk, "registration")).content.decode()
        self.assertNotIn(warning, page, "成本規則適用（2026/10/29）時不警告")
        self.client.post(reverse("registration_save", args=[self.order.pk]),
                         {"registration_date": "2025-12-31", "final_plate_number": "ABC-1234"}, HTTP_X_ORDER_WORKSPACE="1")
        self.order.refresh_from_db()
        self.assertEqual(self.order.registration_county, "")
        page = self.client.get(order_step_url(self.order.pk, "registration")).content.decode()
        self.assertIn(warning, page, "規則 2026/01/01 才生效，領牌日 2025/12/31 找不到規則就要警告（沒有縣市也一樣）")
        SalesOrder.objects.filter(pk=self.order.pk).update(registration_date=None)
        page = self.client.get(order_step_url(self.order.pk, "registration")).content.decode()
        self.assertNotIn(warning, page, "還沒填領牌日不檢查")

    def test_order_page_has_save_state_and_lock_confirm_assets(self):
        page = self.client.get(reverse("order_detail", args=[self.order.pk])).content.decode()
        self.assertEqual(page.count("data-save-chip "), 2, "頁首與精簡列各一個存檔狀態")
        self.assertIn('data-save-alert role="alert" hidden', page)
        self.assertIn("js/lock-confirm.js", page)
        for marker in ("data-save-retry", "data-save-goto", "data-save-discard"):
            self.assertIn(marker, page)


class PrefillTests(TestCase):
    """第 1 層：會影響金額、會鎖定或觸發完成的日期與金額不預填。"""

    from sales.tests import test_order_lifecycle as _lifecycle
    setUp = _lifecycle.OrderLifecycleTests.setUp
    make_order = _lifecycle.OrderLifecycleTests.make_order

    def test_delivery_time_is_blank(self):
        order, _vehicle = self.make_order()
        form = DeliveryCompletionForm(order)
        self.assertNotIn("delivered_at", form.initial)
        # T-138（使用者 2026-11-09）：改選填，留空就不記時間。
        self.assertFalse(form.fields["delivered_at"].required)
        self.assertEqual(form.initial["recipient_name"], order.owner_name, "方便填寫、不影響金額的預設保留")

    def test_deposit_date_blank_and_required_to_confirm(self):
        order, _vehicle = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(deposit_date=None)
        order.refresh_from_db()
        payment = PaymentRecord.objects.filter(order=order, system_key="deposit").first()
        if payment:
            PaymentRecord.objects.filter(pk=payment.pk).update(received_on=None, confirmed=False)
            payment.refresh_from_db()
        form = DepositStepForm(order=order, payment=payment, prefix="deposit")
        self.assertIsNone(form.initial["received_on"])
        bound = DepositStepForm({"deposit-amount": "5000", "deposit-method": "cash", "deposit-confirmed": "on"},
                                order=order, payment=payment, prefix="deposit")
        self.assertFalse(bound.is_valid())
        self.assertIn("received_on", bound.errors)
        self.assertIn("data-lock-confirm", str(form["confirmed"]))
        # 未收妥時改金額不再自動補今天。
        save_deposit_step(order, payment, {"amount": Decimal("5000"), "method": "cash", "received_on": None}, "測試")
        order.refresh_from_db()
        self.assertIsNone(order.deposit_date)

    def test_refund_and_exception_close_need_explicit_values(self):
        order, _vehicle = self.make_order()
        for form_class in (RefundCompletionForm, ExceptionCloseForm):
            form = form_class(order)
            self.assertNotIn("completed_on", form.initial)
            self.assertNotIn("forfeited_amount", form.initial)
            self.assertTrue(form.fields["forfeited_amount"].required, "不沒收要明確填 0")

    def test_overpayment_refund_date_blank(self):
        order, _vehicle = self.make_order()
        summary = {"customer_overpaid": Decimal("100"), "lender_overpaid": Decimal("0")}
        form = OverpaymentRefundForm(order, summary)
        self.assertNotIn("refunded_on", form.initial)
        self.assertEqual(form.initial["amount"], Decimal("100"), "金額保留系統建議值")

    def test_payment_confirm_uses_lock_card(self):
        order, _vehicle = self.make_order()
        payment = PaymentRecord.objects.get(order=order, system_key="balance")
        widget = str(PaymentRecordForm(instance=payment)["confirmed"])
        self.assertIn('data-lock-confirm="確認這筆款項已入帳"', widget)
        self.assertIn('data-lock-required="received_amount received_on payment_method"', widget)


class FrontendContractTests(TestCase):
    """前端行為的關鍵接點（瀏覽器實測見 T-130 回報截圖）。"""

    def test_workspace_routes_status_to_single_chip_and_guards_navigation(self):
        script = (STATIC / "js" / "order-workspace.js").read_text(encoding="utf-8")
        for marker in ("renderSaveState", "flashSaved", "afterSaved(", "async function settle", "saveDiscard",
                       "card.fromElement(field)"):
            self.assertIn(marker, script)
        self.assertNotIn("button.dataset.confirm = '確認完成交付嗎？", script)
        css = (STATIC / "css" / "order-workspace.css").read_text(encoding="utf-8")
        self.assertIn(".workspace-order .autosave-status, .workspace-order [data-autosave-mirror] { display: none !important; }", css)

    def test_lock_confirm_intercepts_submit_before_other_handlers(self):
        script = (STATIC / "js" / "lock-confirm.js").read_text(encoding="utf-8")
        self.assertIn("event.stopImmediatePropagation();", script)
        self.assertIn("}, true);", script, "捕捉階段攔截，早於 form-feedback 與原地送出")
        self.assertNotIn("data-lock-auto", script, "領牌確認卡已拿掉（T-147）")


class WizardDepositAndCountyTests(TestCase):
    """使用者 2026-11-07 決定：建單訂金日期必填不帶今天；領牌縣市從畫面拿掉（資料庫欄位與舊資料保留）。"""

    def test_new_order_form_leaves_deposit_date_blank_and_requires_it(self):
        from sales.forms import SalesOrderForm
        from sales.intake_forms import IntakeOrderForm

        self.assertIsNone(SalesOrderForm().initial.get("deposit_date"))
        self.assertEqual(str(SalesOrderForm(initial={"deposit_date": date(2026, 11, 1)}).initial["deposit_date"]), "2026-11-01",
                         "草稿已填的日期照樣帶回")
        user = get_user_model().objects.create_superuser("t130w", "", "test-pass-123")
        form = IntakeOrderForm(data={"deposit_amount": "3000", "deposit_method": "cash", "deposit_date": ""}, user=user)
        form.is_valid()
        self.assertEqual(form.errors.get("deposit_date"), ["有填訂金時，請填訂金日期。"])

    def test_registration_county_is_gone_from_screens_but_kept_in_db(self):
        from sales.models import SalesOrder as Order
        from sales.reporting.engine import DIMENSIONS
        import sales.services.positioned_template_pdf as print_fields

        self.assertIn("registration_county", [field.name for field in Order._meta.fields], "資料庫欄位保留")
        self.assertNotIn("county", DIMENSIONS)
        source = Path(print_fields.__file__).read_text(encoding="utf-8")
        self.assertNotIn("registration_county", source)
        overview = (Path(settings.BASE_DIR) / "sales" / "services" / "order_overview.py").read_text(encoding="utf-8")
        self.assertNotIn("領牌縣市", overview)
        completion = (Path(settings.BASE_DIR) / "templates" / "sales" / "_registration_completion.html").read_text(encoding="utf-8")
        self.assertNotIn("county", completion)
