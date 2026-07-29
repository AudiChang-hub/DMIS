from datetime import date
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader

from sales.forms import AccessoryLineForm, OtherFeeLineForm, SalesOrderForm
from sales.models import (
    OrderChange,
    SalesOrder,
    Store,
    VehicleColor,
    VehicleInventory,
    VehicleModel,
)


class OrderFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="tester", password="test-pass-123"
        )
        self.store_a = Store.objects.create(name="總店", code="HQ")
        self.store_b = Store.objects.create(name="二店", code="B02")
        self.model = VehicleModel.objects.create(
            brand="測試廠牌", name="通勤 125", energy_type=VehicleModel.EnergyType.GAS
        )
        self.color = VehicleColor.objects.create(
            vehicle_model=self.model, name="白"
        )
        self.vehicle = VehicleInventory.objects.create(
            vehicle_model=self.model,
            color=self.color,
            engine_number="ENG-001",
            ownership_store=self.store_b,
            location_store=self.store_b,
        )

    def make_order(self, signed=False):
        order = SalesOrder(
            owner_name="王小明",
            owner_phone="0912345678",
            owner_address="新北市測試區",
            owner_id_number="A123456789",
            vehicle_model=self.model,
            color=self.color,
            vehicle_price=Decimal("79800"),
            deposit_amount=Decimal("4600"),
            actual_balance=Decimal("75200"),
            id_verified=True,
            status=SalesOrder.Status.ALLOCATION_PENDING,
        )
        if signed:
            order.signed_contract = SimpleUploadedFile(
                "signed.pdf", b"signed contract", content_type="application/pdf"
            )
            order.status = SalesOrder.Status.ALLOCATION_PENDING
        order.save()
        order.calculated_balance = order.calculate_balance()
        order.save(update_fields=["calculated_balance", "updated_at"])
        return order

    def test_unsigned_contract_can_allocate(self):
        order = self.make_order(signed=False)

        order.allocate(self.vehicle)

        self.vehicle.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(self.vehicle.status, VehicleInventory.Status.RESERVED)
        self.assertEqual(order.status, SalesOrder.Status.ALLOCATED)

    def test_edit_page_available_until_delivery(self):
        order = self.make_order()
        self.client.force_login(self.user)

        response = self.client.get(reverse("order_edit", args=[order.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "編輯訂單")
        self.assertContains(response, "變更原因")
        self.assertContains(response, "取消修改")
        self.assertContains(response, "data-cancel-edit")
        self.assertContains(response, "beforeunload")
        self.assertContains(response, "尚有未儲存的修改")

        order.status = SalesOrder.Status.DELIVERED_DOCS_PENDING
        order.save(update_fields=["status", "updated_at"])
        locked = self.client.get(reverse("order_edit", args=[order.pk]))
        self.assertRedirects(locked, reverse("order_detail", args=[order.pk]))

    def test_order_detail_uses_consistent_section_spacing(self):
        css = (
            __import__("pathlib").Path("static/css/app.css").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn(
            ".detail-grid { display: grid; grid-template-columns: 1fr 1fr; margin-bottom: 20px; gap: 20px; }",
            css,
        )

    def test_desktop_and_mobile_use_distinct_page_shells(self):
        from pathlib import Path

        css = Path("static/css/app.css").read_text(encoding="utf-8")
        base = Path("templates/base.html").read_text(encoding="utf-8")
        detail = Path("templates/sales/order_detail.html").read_text(encoding="utf-8")
        form = Path("templates/sales/order_form.html").read_text(encoding="utf-8")

        self.assertIn("--shell-wide: 1680px", css)
        self.assertIn(".page-shell--wide { max-width: var(--shell-wide); }", css)
        self.assertIn("width: min(100% - 24px, 700px)", css)
        self.assertIn('class="app-header-inner"', base)
        self.assertIn("app.css' %}?v={{ app_version }}", base)
        self.assertIn("app-update.js' %}?v={{ app_version }}", base)
        self.assertIn("page-shell--wide", detail)
        self.assertIn("page-shell--form", form)

    def test_forms_provide_field_specific_mobile_keyboard_hints(self):
        order_form = SalesOrderForm()
        accessory_form = AccessoryLineForm()
        fee_form = OtherFeeLineForm()

        self.assertEqual(
            order_form.fields["owner_name"].widget.attrs["lang"], "zh-Hant"
        )
        self.assertEqual(
            order_form.fields["owner_phone"].widget.attrs["inputmode"], "tel"
        )
        self.assertEqual(
            order_form.fields["owner_email"].widget.attrs["inputmode"], "email"
        )
        self.assertEqual(
            order_form.fields["owner_id_number"].widget.attrs["lang"], "en"
        )
        self.assertEqual(
            order_form.fields["vehicle_price"].widget.attrs["inputmode"],
            "decimal",
        )
        self.assertEqual(
            accessory_form.fields["quantity"].widget.attrs["inputmode"],
            "numeric",
        )
        self.assertEqual(
            accessory_form.fields["name"].widget.attrs["lang"], "zh-Hant"
        )
        self.assertEqual(fee_form.fields["name"].widget.attrs["lang"], "zh-Hant")

    def test_edit_order_records_reason_and_before_after_values(self):
        order = self.make_order()
        self.client.force_login(self.user)
        data = {
            "_order_revision": str(order.revision),
            "source_type": "store",
            "source": "",
            "owner_type": "company",
            "owner_name": "王小明有限公司",
            "owner_name_en": "",
            "owner_phone": order.owner_phone,
            "owner_email": "",
            "owner_birth_date": "",
            "owner_nationality": "",
            "owner_address": order.owner_address,
            "owner_id_number": order.owner_id_number,
            "residence_expiry": "",
            "id_verified": "on",
            "vehicle_model": str(self.model.pk),
            "color": str(self.color.pk),
            "vehicle_category": "new",
            "payment_type": "cash",
            "vehicle_price": "80000",
            "plate_insurance_fee": "0",
            "installment_opening_fee": "0",
            "deposit_amount": "4600",
            "deposit_date": str(timezone.localdate()),
            "deposit_method": "",
            "installment_company": "",
            "installment_periods": "0",
            "installment_monthly": "0",
            "is_trade_in_subsidy": "",
            "trade_in_plate": "",
            "old_owner_name": "",
            "subsidy_type": "",
            "old_vehicle_valuation": "0",
            "old_vehicle_tax": "0",
            "plate_choice": "none",
            "watched_numbers": "",
            "plate_preference_note": "",
            "delivery_method": "store_pickup",
            "delivery_destination": "",
            "note": "",
            "change_reason": "客戶要求更正公司名稱",
            "accessories-TOTAL_FORMS": "1",
            "accessories-INITIAL_FORMS": "0",
            "accessories-MIN_NUM_FORMS": "0",
            "accessories-MAX_NUM_FORMS": "1000",
            "accessories-0-name": "",
            "accessories-0-quantity": "",
            "accessories-0-line_type": "",
            "accessories-0-amount": "",
            "other_fees-TOTAL_FORMS": "1",
            "other_fees-INITIAL_FORMS": "0",
            "other_fees-MIN_NUM_FORMS": "0",
            "other_fees-MAX_NUM_FORMS": "1000",
            "other_fees-0-name": "",
            "other_fees-0-amount": "",
        }

        response = self.client.post(reverse("order_edit", args=[order.pk]), data)

        self.assertRedirects(response, reverse("order_detail", args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.owner_name, "王小明有限公司")
        self.assertEqual(order.revision, 2)
        self.assertEqual(order.actual_balance, Decimal("75400"))
        self.assertEqual(order.balance_adjustment_reason, "客戶要求更正公司名稱")
        change = order.changes.get()
        self.assertEqual(change.reason, "客戶要求更正公司名稱")
        self.assertEqual(
            change.changes["車主姓名／公司名稱"],
            {"before": "王小明", "after": "王小明有限公司"},
        )

        detail = self.client.get(reverse("order_detail", args=[order.pk]))
        self.assertContains(detail, "tester")
        self.assertContains(detail, "修改了")
        self.assertContains(detail, "客戶要求更正公司名稱")
        self.assertContains(detail, "王小明有限公司")
        self.assertNotContains(detail, "owner_name")

    def test_change_history_translates_codes_money_and_line_items(self):
        order = self.make_order()
        OrderChange.objects.create(
            order=order,
            actor_name="王行政",
            reason="依客戶確認內容調整",
            changes={
                "主要付款方式": {"before": "installment", "after": "cash"},
                "訂金": {"before": "5000", "after": "8000"},
                "選號方式": {"before": "none", "after": "preference"},
                "配件": {
                    "before": [],
                    "after": [
                        {
                            "名稱": "手機架",
                            "數量": 1,
                            "類型": "加購",
                            "金額": "850",
                            "安裝日期": "",
                            "備註": "",
                        }
                    ],
                },
            },
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("order_detail", args=[order.pk]))

        self.assertContains(response, "王行政")
        self.assertContains(response, "依客戶確認內容調整")
        self.assertContains(response, "分期")
        self.assertContains(response, "現金")
        self.assertContains(response, "$5,000")
        self.assertContains(response, "$8,000")
        self.assertContains(response, "一般領牌偏好")
        self.assertContains(response, "手機架 × 1")
        self.assertNotContains(response, "installment")
        self.assertNotContains(response, "preference")
        self.assertNotContains(response, "&#x27;名稱&#x27;")

    def test_signed_contract_can_allocate_and_locks_vehicle(self):
        order = self.make_order(signed=True)

        order.allocate(self.vehicle)

        order.refresh_from_db()
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.status, VehicleInventory.Status.RESERVED)
        self.assertEqual(order.allocated_vehicle, self.vehicle)
        self.assertEqual(order.status, SalesOrder.Status.ALLOCATED)

    def test_same_vehicle_cannot_allocate_twice(self):
        first = self.make_order(signed=True)
        second = self.make_order(signed=True)
        first.allocate(self.vehicle)

        with self.assertRaisesMessage(ValidationError, "目前不可配車"):
            second.allocate(self.vehicle)

    def test_gas_vehicle_requires_engine_number(self):
        vehicle = VehicleInventory(
            vehicle_model=self.model,
            color=self.color,
            frame_number="FRAME-WRONG",
            ownership_store=self.store_a,
            location_store=self.store_a,
        )

        with self.assertRaises(ValidationError) as context:
            vehicle.full_clean()

        self.assertIn("engine_number", context.exception.message_dict)

    def test_dashboard_global_searches_phone_suffix(self):
        order = self.make_order()
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard"), {"q": "5678"})

        self.assertContains(response, order.owner_name)
        self.assertContains(response, order.number)

    def test_contract_print_returns_two_page_dynamic_pdf(self):
        order = self.make_order()
        self.client.force_login(self.user)

        response = self.client.get(reverse("contract_print", args=[order.pk]))
        content = b"".join(response.streaming_content)
        reader = PdfReader(BytesIO(content))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("inline;", response["Content-Disposition"])
        self.assertEqual(len(reader.pages), 2)
        extracted = "\n".join(page.extract_text() for page in reader.pages)
        self.assertIn(order.number, extracted)
        self.assertIn(order.owner_name, extracted)
        self.assertIn("店家留存聯", extracted)
        self.assertIn("客戶留存聯", extracted)
        self.assertIn("財產登記制", extracted)
        self.assertIn("領牌後無法辦理退換貨", extracted)

    def test_privacy_consent_uses_latest_order_name_date_and_plate(self):
        order = self.make_order()
        order.owner_name = "馮華微"
        order.order_date = date(2026, 7, 29)
        order.final_plate_number = "ABC-1234"
        order.save()
        self.client.force_login(self.user)

        response = self.client.get(reverse("privacy_consent_print", args=[order.pk]))
        content = b"".join(response.streaming_content)
        reader = PdfReader(BytesIO(content))
        extracted = "\n".join(page.extract_text() for page in reader.pages)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(reader.pages), 1)
        self.assertIn("馮華微", extracted)
        self.assertIn("ABC-1234", extracted)
        self.assertIn("中華民國 115 年 07 月 29 日", extracted)
        self.assertIn("馭盛國際有限公司", extracted)

        order.owner_name = "馮華薇"
        order.order_date = date(2026, 8, 1)
        order.save()
        updated_response = self.client.get(
            reverse("privacy_consent_print", args=[order.pk])
        )
        updated_content = b"".join(updated_response.streaming_content)
        updated_text = "\n".join(
            page.extract_text()
            for page in PdfReader(BytesIO(updated_content)).pages
        )
        self.assertIn("馮華薇", updated_text)
        self.assertIn("中華民國 115 年 08 月 01 日", updated_text)
        self.assertNotIn("馮華微", updated_text)

    def test_combined_signing_documents_have_three_pages(self):
        order = self.make_order()
        self.client.force_login(self.user)

        response = self.client.get(reverse("order_documents_print", args=[order.pk]))
        content = b"".join(response.streaming_content)
        reader = PdfReader(BytesIO(content))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(reader.pages), 3)

        detail = self.client.get(
            reverse("order_detail", args=[order.pk]),
            {"created": "1"},
        )
        self.assertContains(detail, "列印個資同意書")
        self.assertContains(detail, "全部一起列印")
        self.assertContains(detail, "一鍵列印全部文件")
        self.assertContains(detail, "單獨列印訂購合約")
        self.assertContains(detail, "單獨列印個資同意書")
        self.assertContains(detail, "個資同意書附件")
        self.assertContains(detail, reverse("privacy_consent_upload", args=[order.pk]))

    def test_privacy_consent_can_be_uploaded_separately(self):
        order = self.make_order()
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("privacy_consent_upload", args=[order.pk]),
            {
                "privacy_consent": SimpleUploadedFile(
                    "privacy.pdf",
                    b"signed privacy consent",
                    content_type="application/pdf",
                )
            },
        )

        self.assertRedirects(response, reverse("order_detail", args=[order.pk]))
        order.refresh_from_db()
        self.assertTrue(order.has_privacy_consent)
        self.assertIsNotNone(order.privacy_consent_uploaded_at)
        self.assertTrue(
            order.events.filter(description__contains="個資同意書").exists()
        )

    def test_mobile_order_and_inventory_pages_render(self):
        self.client.force_login(self.user)

        order_response = self.client.get(reverse("order_create"))
        inventory_response = self.client.get(reverse("inventory_create"))

        self.assertEqual(order_response.status_code, 200)
        self.assertContains(order_response, "建立新訂單")
        self.assertContains(order_response, "訂單建檔")
        self.assertNotContains(order_response, "手機下單")
        self.assertContains(order_response, "editing-presence")
        self.assertContains(order_response, "refreshDraftPresence")
        self.assertContains(order_response, "自動辨識姓名")
        self.assertContains(order_response, "移除正面照片")
        self.assertContains(order_response, "移除反面照片")
        self.assertContains(order_response, "ocrRequestVersion")
        self.assertContains(order_response, "requestPhotoVersion")
        self.assertContains(order_response, "showSavedPhoto")
        self.assertContains(order_response, "正在辨識證件")
        self.assertContains(order_response, 'aria-current="step"')
        self.assertContains(order_response, "updateActiveSection")
        self.assertNotContains(order_response, "data-save-draft")
        self.assertNotContains(order_response, ">暫存</button>")
        content = order_response.content.decode()
        self.assertGreater(
            content.index('id="add-accessory"'),
            content.index('id="accessory-forms"'),
        )
        self.assertGreater(
            content.index('id="add-other-fee"'),
            content.index('id="other-fee-forms"'),
        )
        self.assertContains(order_response, 'class="accessory-row"')
        self.assertContains(order_response, "或從手機相簿選擇圖片")
        self.assertContains(order_response, "＋ 新增費用")
        self.assertContains(order_response, "現金")
        self.assertContains(order_response, "分期")
        self.assertContains(order_response, "刷卡")
        self.assertContains(order_response, "分期公司")
        self.assertContains(order_response, "分期期數")
        self.assertContains(order_response, "分期開辦費")
        self.assertContains(order_response, "每期金額")
        self.assertContains(order_response, "送達地點／託運目的地")
        self.assertTrue(order_response.context["form"]["plate_choice"].field.required)
        self.assertTrue(order_response.context["form"]["delivery_method"].field.required)
        self.assertFalse(
            order_response.context["form"]["old_vehicle_valuation"].field.required
        )
        self.assertFalse(
            order_response.context["form"]["old_vehicle_tax"].field.required
        )
        self.assertNotContains(order_response, "分期申請金額")
        self.assertNotContains(order_response, "分期申請日期")
        self.assertNotContains(order_response, "核准／拒絕日期")
        self.assertLess(content.index("分期資料"), content.index("其他費用"))
        self.assertNotContains(order_response, "折扣／抵扣")
        self.assertEqual(
            order_response.context["form"]["deposit_date"].value(),
            timezone.localdate(),
        )
        for field_name in (
            "vehicle_price",
            "plate_insurance_fee",
            "deposit_amount",
            "installment_periods",
            "installment_opening_fee",
            "installment_monthly",
            "old_vehicle_valuation",
            "old_vehicle_tax",
        ):
            self.assertIsNone(order_response.context["form"][field_name].value())
        self.assertIsNone(
            order_response.context["formset"].forms[0]["amount"].value()
        )
        self.assertEqual(
            order_response.context["formset"].forms[0]["quantity"].value(), 1
        )
        self.assertContains(
            order_response,
            f'value="{timezone.localdate():%Y-%m-%d}"',
        )
        self.assertLess(content.index("id_id_front"), content.index("id_owner_name"))
        self.assertNotIn('capture="environment"', content)
        self.assertContains(order_response, 'type="date"')
        self.assertEqual(inventory_response.status_code, 200)
        self.assertContains(inventory_response, "新增進車")

    def test_delivery_destination_is_required_only_for_delivery_or_carrier(self):
        required_data = {
            "delivery_method": SalesOrder.DeliveryMethod.DIRECT_DELIVERY,
        }
        direct_delivery_form = SalesOrderForm(data=required_data)
        direct_delivery_form.is_valid()
        self.assertIn(
            "delivery_destination", direct_delivery_form.errors
        )

        carrier_form = SalesOrderForm(
            data={"delivery_method": SalesOrder.DeliveryMethod.CARRIER}
        )
        carrier_form.is_valid()
        self.assertIn("delivery_destination", carrier_form.errors)

        pickup_form = SalesOrderForm(
            data={"delivery_method": SalesOrder.DeliveryMethod.STORE_PICKUP}
        )
        pickup_form.is_valid()
        self.assertNotIn("delivery_destination", pickup_form.errors)

    def test_accessory_fields_are_required_only_after_name_is_entered(self):
        empty_form = AccessoryLineForm(
            data={"name": "", "quantity": "", "line_type": "", "amount": ""}
        )
        self.assertTrue(empty_form.is_valid())
        self.assertFalse(empty_form.fields["name"].required)
        self.assertFalse(empty_form.fields["quantity"].required)
        self.assertFalse(empty_form.fields["line_type"].required)
        self.assertFalse(empty_form.fields["amount"].required)

        named_form = AccessoryLineForm(
            data={"name": "後箱", "quantity": "", "line_type": "", "amount": ""}
        )
        self.assertFalse(named_form.is_valid())
        self.assertIn("quantity", named_form.errors)
        self.assertIn("line_type", named_form.errors)
        self.assertIn("amount", named_form.errors)

    def test_app_version_endpoint_is_not_cached(self):
        response = self.client.get(reverse("app_version"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["version"]), 12)
        self.assertIn("no-store", response["Cache-Control"])

    def test_authenticated_page_contains_update_controls(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "檢查系統更新")
        self.assertContains(response, "app-update-banner")
        self.assertContains(response, "js/app-update")
