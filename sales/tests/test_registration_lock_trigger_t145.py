"""T-145（使用者 2026-11-11 選 A）：領牌完成只看領牌日與車牌，行照、登記書改選填（取代 2026-10-22 T-95）。

起因：上傳領牌文件時跳出「確認後會鎖定」，使用者以為上傳會鎖定。
- 領牌日與車牌都填好（自動儲存剛齊全）時跳出確認卡，只跳一次；上傳文件不再觸發，也不是完成條件。
- 確認卡選完都留在原畫面：確認走原地送出後回到同一步驟與位置，不導到別的步驟。
- 鎖定範圍不變：領牌日、車牌、成本、獎勵、傭金、待交車。
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

from sales.models import (
    RegistrationDocument,
    SalesOrder,
    Store,
    VehicleColor,
    VehicleInventory,
    VehicleModel,
    VehicleSettlementCostRule,
)
from sales.services.order_steps import order_step_url
from sales.tests.test_inplace_uploads import png

Doc = RegistrationDocument.DocumentType
STATIC = Path(settings.BASE_DIR) / "static"


class RegistrationLockTriggerTests(TestCase):
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

        self.user = get_user_model().objects.create_superuser("t145", "", "test-pass-123")
        self.client.force_login(self.user)
        store = Store.objects.create(name="總店", code="HQ")
        model = VehicleModel.objects.create(brand="SUZUKI", name="SUI 125", energy_type=VehicleModel.EnergyType.GAS)
        color = VehicleColor.objects.create(vehicle_model=model, name="灰")
        VehicleSettlementCostRule.objects.create(vehicle_model=model, amount=Decimal("60000"), effective_from=date(2026, 1, 1))
        self.order = SalesOrder(
            owner_name="測試車主", owner_phone="0900000000", owner_address="測試地址", owner_id_number="A100000001",
            vehicle_model=model, color=color, vehicle_price=Decimal("75000"), deposit_amount=Decimal("5000"),
            actual_balance=Decimal("70000"), id_verified=True, status=SalesOrder.Status.ALLOCATION_PENDING,
        )
        initialize_company(self.order, self.user)
        self.order.save()
        vehicle = VehicleInventory.objects.create(
            vehicle_model=model, color=color, engine_number="ENG-T145", ownership_store=store, location_store=store,
        )
        self.order.allocate(vehicle)
        self.save_url = reverse("registration_save", args=[self.order.pk])

    def autosave(self, **data):
        payload = {"registration_date": "", "final_plate_number": "", **data}
        return self.client.post(self.save_url, payload, HTTP_X_ORDER_WORKSPACE="1").json()

    def upload(self, document_type, **headers):
        return self.client.post(
            reverse("registration_document_upload", args=[self.order.pk]),
            {"document_type": document_type, "file": png()}, **headers,
        )

    def test_documents_are_not_registration_requirements(self):
        self.assertEqual(self.order.required_registration_document_types(), set())
        self.order.registration_date = date(2026, 11, 10)
        self.order.final_plate_number = "ABC-1234"
        self.order.save(update_fields=["registration_date", "final_plate_number", "updated_at"])
        self.assertEqual(self.order.missing_registration_requirements(), [], "沒有行照、登記書也算齊全")

    def test_date_only_does_not_offer_card(self):
        response = self.client.post(
            self.save_url, {"registration_date": "2026-11-10", "final_plate_number": ""}, HTTP_X_ORDER_WORKSPACE="1",
        )
        # 車牌必填，只填日期時這次存檔不成立，也不跳卡。
        self.assertNotIn("data-lock-auto", response.content.decode())
        self.order.refresh_from_db()
        self.assertEqual(self.order.missing_registration_requirements(), ["實際領牌日期", "車牌號碼"])

    def test_date_and_plate_offer_card_once_without_documents(self):
        first = self.autosave(registration_date="2026-11-10", final_plate_number="abc-1234")
        self.assertIn("data-lock-auto", first["registration_html"], "日期與車牌都填好就跳卡")
        self.assertIn("<dt>領牌文件</dt><dd>已上傳 0 份（選填）</dd>", first["registration_html"])
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_registration_complete, "跳卡不等於鎖定")
        # 選「先不要」後繼續自動儲存：不再跳。
        again = self.autosave(registration_date="2026-11-10", final_plate_number="abc-1235")
        self.assertNotIn("data-lock-auto", again["registration_html"])
        page = self.client.get(order_step_url(self.order.pk, "registration")).content.decode()
        self.assertNotIn("data-lock-auto", page)
        self.assertIn('data-lock-confirm="確認領牌完成"', page, "按鈕仍可隨時按")

    def test_uploads_never_trigger_card(self):
        # 資料未齊：上傳不跳。
        for doc_type in (Doc.NEW_LICENSE, Doc.REGISTRATION_APPLICATION):
            self.assertNotIn("confirm=", self.upload(doc_type)["Location"])
        payload = self.upload(Doc.INVOICE, HTTP_X_REQUESTED_WITH="XMLHttpRequest").json()
        self.assertNotIn("confirm=", payload["redirect_url"])
        # 資料已齊（卡片已跳過）：再上傳或替換也不跳。
        self.autosave(registration_date="2026-11-10", final_plate_number="ABC-1234")
        self.assertNotIn("confirm=", self.upload(Doc.NEW_LICENSE)["Location"])

    def test_confirm_locks_without_documents_and_stays_on_registration_step(self):
        self.autosave(registration_date="2026-11-10", final_plate_number="ABC-1234")
        response = self.client.post(reverse("registration_complete", args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_registration_complete)
        self.assertEqual(self.order.status, SalesOrder.Status.DELIVERY_PENDING)
        profile = self.order.operations
        self.assertIsNotNone(profile.vehicle_cost_locked_at)
        self.assertIsNotNone(profile.incentive_locked_at)
        # 沒有 JavaScript 時也回到領牌步驟，不跳到其他步驟。
        self.assertEqual(response["Location"], order_step_url(self.order.pk, "registration"))
        # 鎖定行為不變：日期與車牌不能再改。
        blocked = self.client.post(
            self.save_url, {"registration_date": "2026-11-11", "final_plate_number": "XYZ-0001"}, HTTP_X_ORDER_WORKSPACE="1",
        )
        self.assertEqual(blocked.status_code, 409)
        self.order.refresh_from_db()
        self.assertEqual((self.order.registration_date, self.order.final_plate_number), (date(2026, 11, 10), "ABC-1234"))

    def test_confirm_form_submits_in_place_and_reloads_to_same_position(self):
        self.autosave(registration_date="2026-11-10", final_plate_number="ABC-1234")
        page = self.client.get(order_step_url(self.order.pk, "registration")).content.decode()
        start = page.index('action="%s"' % reverse("registration_complete", args=[self.order.pk]))
        form_tag = page[page.rindex("<form", 0, start):page.index(">", start)]
        self.assertIn("data-inplace-form", form_tag)
        self.assertIn('data-inplace-success="reload"', form_tag)

    def test_documents_marked_optional_on_page(self):
        page = self.client.get(order_step_url(self.order.pk, "registration")).content.decode()
        self.assertNotIn("領牌需要</span>", page)
