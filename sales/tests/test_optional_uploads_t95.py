"""所有上傳改為選填（使用者 2026-10-22 T-95）。

只有新行照照片、新車領牌登記書是領牌完成的條件；強制險單、補助文件、簽署文件都不卡任何關卡，
附件分頁與訂單頁同一規則：領牌後已上傳的鎖定、還沒上傳的仍可補傳。
"""

import shutil
import tempfile
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from sales.models import (
    RegistrationDocument,
    SalesOrder,
    Store,
    SubsidyItem,
    VehicleColor,
    VehicleInventory,
    VehicleModel,
    VehicleSettlementCostRule,
)
from sales.services.order_attachments import document_slots, group_slots
from sales.services.order_steps import build_order_steps
from sales.tests.test_inplace_uploads import png

Doc = RegistrationDocument.DocumentType


class OptionalUploadTests(TestCase):
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

        self.user = get_user_model().objects.create_superuser("t95", "", "test-pass-123")
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
            vehicle_model=model, color=color, engine_number="ENG-T95", ownership_store=store, location_store=store,
        )
        self.order.allocate(vehicle)
        self.order.registration_date = date(2026, 10, 19)
        self.order.final_plate_number = "ABC-1234"
        self.order.save(update_fields=["registration_date", "final_plate_number", "updated_at"])

    def upload(self, document_type):
        return self.client.post(
            reverse("registration_document_upload", args=[self.order.pk]),
            {"document_type": document_type, "file": png()},
        )

    def slots(self, **rows):
        request = self.client.get(reverse("order_detail", args=[self.order.pk])).wsgi_request
        return group_slots(document_slots(self.order, request, **rows))

    def test_license_and_application_complete_registration_without_insurance(self):
        self.assertEqual(self.order.required_registration_document_types(), {Doc.NEW_LICENSE, Doc.REGISTRATION_APPLICATION})
        self.upload(Doc.NEW_LICENSE)
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_registration_complete)
        self.assertEqual(self.order.missing_registration_requirements(), ["新車領牌登記書"])
        self.upload(Doc.REGISTRATION_APPLICATION)
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_registration_complete)
        self.assertEqual(self.order.status, SalesOrder.Status.DELIVERY_PENDING)
        self.assertFalse(self.order.registration_documents.filter(document_type=Doc.COMPULSORY_INSURANCE).exists())

    def test_missing_documents_can_be_added_after_registration_but_uploaded_ones_stay_locked(self):
        self.upload(Doc.NEW_LICENSE)
        self.upload(Doc.REGISTRATION_APPLICATION)
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_registration_complete)
        rows = [
            {"type": t, "label": Doc(t).label, "required": t in self.order.required_registration_document_types(),
             "document": self.order.registration_documents.filter(document_type=t).first()}
            for t in RegistrationDocument.active_fixed_document_types()
        ]
        slots = {slot.document_type: slot for group in self.slots(registration_rows=rows) for slot in group["slots"]}
        self.assertFalse(slots[Doc.NEW_LICENSE].open)
        self.assertTrue(slots[Doc.COMPULSORY_INSURANCE].open)
        self.assertFalse(slots[Doc.COMPULSORY_INSURANCE].required)
        self.assertEqual(slots[Doc.COMPULSORY_INSURANCE].status, "未上傳")
        self.assertEqual(self.upload(Doc.COMPULSORY_INSURANCE).status_code, 302)
        self.assertTrue(self.order.registration_documents.filter(document_type=Doc.COMPULSORY_INSURANCE).exists())
        self.assertEqual(self.upload(Doc.NEW_LICENSE).status_code, 302)
        self.assertEqual(self.order.registration_documents.filter(document_type=Doc.NEW_LICENSE).count(), 1)

    def test_page_marks_only_registration_documents_as_needed(self):
        html = self.client.get(reverse("order_detail", args=[self.order.pk])).content.decode()
        self.assertEqual(html.count("領牌需要</span>"), 4)  # 領牌步驟與附件分頁各兩份
        self.assertNotIn("必填</span>", html.split('id="order-files"')[1].split("</section>")[0])

    def test_signatures_are_optional_step(self):
        steps = build_order_steps(self.order)["steps"]
        self.assertEqual(steps["documents"]["state"], "optional")
        self.assertEqual(steps["documents"]["state_label"], "選用")
        groups = {group["title"]: group for group in self.slots()}
        self.assertEqual(groups["簽署文件"]["missing"], 0)
        self.assertTrue(all(slot.status == "未上傳" for slot in groups["簽署文件"]["slots"]))

    def test_subsidy_is_ready_with_data_only_and_reports_document_progress(self):
        SalesOrder.objects.filter(pk=self.order.pk).update(is_trade_in_subsidy=True, trade_in_plate="OLD-001")
        self.order.refresh_from_db()
        SubsidyItem.objects.create(order=self.order, category=SubsidyItem.Category.choices[0][0], item_name="汰舊換新", expected_amount=Decimal("5000"))
        self.assertEqual(self.order.missing_subsidy_requirements(), [])
        self.assertTrue(self.order.is_subsidy_ready)
        uploaded, expected = self.order.subsidy_document_progress()
        self.assertGreater(expected, 0)
        self.assertLess(uploaded, expected)
        html = self.client.get(reverse("order_detail", args=[self.order.pk])).content.decode()
        self.assertIn("補助基本資料已齊全", html)
        self.assertIn(f"補助文件已上傳 {uploaded}／{expected}（選填）", html)

    def test_dealer_delivered_before_registration_reads_awaiting_registration(self):
        self.assertEqual(SalesOrder.Status.DELIVERED_DOCS_PENDING.label, "已交車／待領牌")
