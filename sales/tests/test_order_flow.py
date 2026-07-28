from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import (
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
            status=SalesOrder.Status.CONTRACT_PENDING,
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

    def test_unsigned_contract_cannot_allocate(self):
        order = self.make_order(signed=False)

        with self.assertRaisesMessage(ValidationError, "尚未上傳已簽署合約"):
            order.allocate(self.vehicle)

        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.status, VehicleInventory.Status.AVAILABLE)

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

    def test_mobile_order_and_inventory_pages_render(self):
        self.client.force_login(self.user)

        order_response = self.client.get(reverse("order_create"))
        inventory_response = self.client.get(reverse("inventory_create"))

        self.assertEqual(order_response.status_code, 200)
        self.assertContains(order_response, "建立新訂單")
        self.assertContains(order_response, "自動辨識姓名")
        self.assertContains(order_response, "移除正面照片")
        self.assertContains(order_response, "移除反面照片")
        self.assertContains(order_response, "ocrRequestVersion")
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
