"""領牌步驟「其他領牌相關資料」：一次多檔、名稱帶原始檔名、選填（使用者 2026-10-22 T-101）。

同一張訂單可存多份（唯一限制放寬，0197），不算領牌完成條件；領牌完成後仍可上傳與刪除，附件分頁看得到。
"""

import shutil
import tempfile
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
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
from sales.services.order_attachments import collect_order_file_groups
from sales.tests.test_inplace_uploads import png

Doc = RegistrationDocument.DocumentType


class RegistrationOtherDocumentTests(TestCase):
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

        self.user = get_user_model().objects.create_superuser("t101", "", "test-pass-123")
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
            vehicle_model=model, color=color, engine_number="ENG-T101", ownership_store=store, location_store=store,
        )
        self.order.allocate(vehicle)
        self.url = reverse("registration_document_upload", args=[self.order.pk])

    def upload(self, file, **extra):
        return self.client.post(
            self.url, {"document_type": Doc.OTHER, "file": file},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest", HTTP_ACCEPT="application/json", **extra,
        )

    def others(self):
        return list(self.order.registration_documents.filter(document_type=Doc.OTHER).order_by("pk"))

    def test_multiple_files_each_saved_with_original_name(self):
        for name in ("監理站收據.png", "選號截圖.png"):
            response = self.upload(png(name))
            self.assertEqual(response.status_code, 200, response.content)
            self.assertTrue(response.json()["ok"])
        pdf = SimpleUploadedFile("委託書.pdf", b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF", content_type="application/pdf")
        self.assertTrue(self.upload(pdf).json()["ok"])
        self.assertEqual([doc.name for doc in self.others()], ["監理站收據", "選號截圖", "委託書"])

    def test_rejects_executable_with_reason(self):
        response = self.upload(SimpleUploadedFile("bad.exe", b"MZ", content_type="application/octet-stream"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("文件上傳失敗：", response.json()["message"])
        self.assertEqual(self.others(), [])

    def test_optional_and_kept_after_registration_completes(self):
        self.upload(png("補充.png"))
        self.assertNotIn(Doc.OTHER, self.order.required_registration_document_types())
        SalesOrder.objects.filter(pk=self.order.pk).update(registration_date=date(2026, 10, 19), final_plate_number="ABC-1234")
        for document_type in (Doc.NEW_LICENSE, Doc.REGISTRATION_APPLICATION):
            self.client.post(self.url, {"document_type": document_type, "file": png()})
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_registration_complete)
        # 領牌完成後仍可再上傳、也可刪除傳錯的補充檔；固定文件照舊鎖定。
        self.assertTrue(self.upload(png("晚到收據.png")).json()["ok"])
        self.assertEqual(len(self.others()), 2)
        mistake = self.others()[-1]
        self.client.post(reverse("registration_document_delete", args=[self.order.pk, mistake.pk]))
        self.assertEqual(len(self.others()), 1)
        license_doc = self.order.registration_documents.get(document_type=Doc.NEW_LICENSE)
        self.client.post(reverse("registration_document_delete", args=[self.order.pk, license_doc.pk]))
        self.assertTrue(RegistrationDocument.objects.filter(pk=license_doc.pk).exists())

    def test_page_block_and_attachments_listing(self):
        self.upload(png("監理站收據.png"))
        response = self.client.get(reverse("order_detail", args=[self.order.pk]))
        html = response.content.decode()
        self.assertIn('id="other-registration-upload"', html)
        self.assertIn("其他領牌相關資料", html)
        self.assertRegex(html, r'<form[^>]*id="other-registration-upload"[^>]*data-multi-upload')
        self.assertIn('name="document_type" value="other"', html)
        self.assertIn("監理站收據", html)
        groups = collect_order_file_groups(self.order, response.wsgi_request)
        registration = next(group for group in groups if group["title"] == "領牌文件")
        self.assertIn("監理站收據", [item.label for item in registration["files"]])
