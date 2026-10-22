"""上傳不重新整理、不捲動（使用者 2026-10-19）。

前端（static/js/inplace-regions.js）把導回頁面中同 id 的 data-inplace-region 區塊換進目前畫面；
這裡守住伺服器端的前提：區塊標記穩定存在、表單標記正確、非 JS 送出照舊導回，
而且單純上傳／刪除檔案不會改動訂單與收支的版本號（否則原地更新後，其他區塊的自動儲存會誤判衝突）。
"""

import re
import shutil
import tempfile
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from sales.models import (
    OrderOperationsProfile,
    PositionedPrintTemplate,
    RegistrationDocument,
    SalesOrder,
    Store,
    SubsidyDocument,
    VehicleColor,
    VehicleInventory,
    VehicleModel,
)

ORDER_REGIONS = (
    "order-status-pill",
    "signed-documents-status",
    "signed-documents-files",
    "registration-documents",
    "registration-completion",
    "subsidy-stage-status",
    "subsidy-documents",
    "subsidy-completion",
    "order-files",
)


def png(name="photo.png"):
    stream = BytesIO()
    Image.new("RGB", (32, 24), "white").save(stream, format="PNG")
    return SimpleUploadedFile(name, stream.getvalue(), content_type="image/png")


def region_ids(html):
    return re.findall(r'id="([^"]+)"[^>]*\bdata-inplace-region\b', html)


class InplaceUploadTests(TestCase):
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

        self.user = get_user_model().objects.create_user(username="uploader", password="test-pass-123")
        self.client.force_login(self.user)
        store = Store.objects.create(name="總店", code="HQ")
        model = VehicleModel.objects.create(brand="SUZUKI", name="SUI 125", energy_type=VehicleModel.EnergyType.GAS)
        color = VehicleColor.objects.create(vehicle_model=model, name="灰")
        self.order = SalesOrder(
            owner_name="王小明", owner_phone="0912345678", owner_address="新北市汐止區", owner_id_number="A123456789",
            vehicle_model=model, color=color, vehicle_price=Decimal("75000"), deposit_amount=Decimal("5000"),
            actual_balance=Decimal("70000"), id_verified=True, is_trade_in_subsidy=True,
            status=SalesOrder.Status.ALLOCATION_PENDING,
        )
        initialize_company(self.order, self.user)
        self.order.save()
        self.order.calculated_balance = self.order.calculate_balance()
        self.order.save(update_fields=["calculated_balance", "updated_at"])
        vehicle = VehicleInventory.objects.create(
            vehicle_model=model, color=color, engine_number="ENG-IP1", ownership_store=store, location_store=store,
        )
        self.order.allocate(vehicle)
        self.detail_url = reverse("order_detail", args=[self.order.pk])

    def detail(self):
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def versions(self):
        self.order.refresh_from_db()
        profile = OrderOperationsProfile.objects.filter(order=self.order).first()
        return self.order.revision, profile.updated_at if profile else None

    def test_order_page_marks_each_upload_region_once(self):
        html = self.detail()
        ids = region_ids(html)
        for region in ORDER_REGIONS:
            self.assertEqual(ids.count(region), 1, region)
            self.assertEqual(html.count(f'id="{region}"'), 1, region)
        # 原地更新的腳本要比訂單工作區先載入，重新載入後才能回到原位置。
        self.assertLess(html.index("js/inplace-regions.js"), html.index("js/order-workspace.js"))
        self.assertIn("js/document-upload-progress.js", html)

    def test_forms_inside_regions_submit_in_place(self):
        insurance = RegistrationDocument.objects.create(
            order=self.order, document_type=RegistrationDocument.DocumentType.OTHER_INSURANCE,
            name="第三人責任險", file=png("policy.png"),
        )
        subsidy = SubsidyDocument.objects.create(
            order=self.order, document_type="other", name="切結書", file=png("note.png"),
        )
        self.client.post(reverse("order_attachment_upload", args=[self.order.pk]), {"files": png("extra.png")})
        attachment = self.order.other_attachments.get()
        html = self.detail()
        for marker in (
            '<form class="other-insurance__form" data-inplace-form',
            '<form class="other-subsidy-documents__form" id="other-subsidy-upload" data-multi-upload',
            f'action="{reverse("registration_document_delete", args=[self.order.pk, insurance.pk])}" data-inplace-form',
            f'action="{reverse("subsidy_document_delete", args=[self.order.pk, subsidy.pk])}" data-inplace-form',
            f'action="{reverse("order_attachment_delete", args=[self.order.pk, attachment.pk])}" data-inplace-form',
            '<form class="order-file__classify" data-inplace-form',
        ):
            self.assertIn(marker, html)
        # 1.86.30：訂金步驟改用訂單頁自動儲存（已收妥開關），不再是原地送出後重新載入的區塊。
        self.assertIn('data-workspace-save="deposit"', html)
        self.assertNotIn('data-inplace-region id="deposit-payment"', html)

    def test_regions_survive_upload_and_delete(self):
        before = region_ids(self.detail())
        response = self.client.post(
            reverse("registration_document_upload", args=[self.order.pk]),
            {"document_type": RegistrationDocument.DocumentType.OTHER_INSURANCE, "name": "竊盜險", "file": png()},
            HTTP_X_INPLACE_FORM="1", HTTP_ACCEPT="text/html",
        )
        self.assertEqual(response.status_code, 302)
        after = region_ids(self.detail())
        self.assertEqual(before, after)
        document = RegistrationDocument.objects.get(order=self.order, name="竊盜險")
        self.client.post(reverse("registration_document_delete", args=[self.order.pk, document.pk]), HTTP_X_INPLACE_FORM="1")
        self.assertEqual(region_ids(self.detail()), before)

    def test_without_javascript_uploads_still_redirect_with_message(self):
        response = self.client.post(
            reverse("registration_document_upload", args=[self.order.pk]),
            {"document_type": RegistrationDocument.DocumentType.OTHER_INSURANCE, "name": "強制險", "file": png()},
            follow=True,
        )
        self.assertEqual(response.redirect_chain[-1][1], 302)
        self.assertEqual(response.request["PATH_INFO"], self.detail_url)
        self.assertContains(response, "強制險已上傳")
        self.assertContains(response, 'id="registration-documents"')

    def test_rejected_upload_reports_error_message_in_redirected_page(self):
        # 前端靠導回頁面的錯誤訊息判斷「未完成」，原表單與已填內容留在原地。
        response = self.client.post(
            reverse("registration_document_upload", args=[self.order.pk]),
            {"document_type": RegistrationDocument.DocumentType.OTHER_INSURANCE, "name": "壞檔",
             "file": SimpleUploadedFile("bad.exe", b"MZ", content_type="application/octet-stream")},
            follow=True,
        )
        self.assertContains(response, 'class="message error"')
        self.assertFalse(RegistrationDocument.objects.filter(order=self.order, name="壞檔").exists())

    def test_json_upload_still_returns_redirect_url_for_refresh(self):
        response = self.client.post(
            reverse("registration_document_upload", args=[self.order.pk]),
            {"document_type": RegistrationDocument.DocumentType.OTHER_INSURANCE, "name": "保單", "file": png()},
            HTTP_ACCEPT="application/json", HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["redirect_url"].startswith(self.detail_url))

    def test_file_uploads_do_not_change_versions_used_by_autosave(self):
        before = self.versions()
        self.client.post(
            reverse("registration_document_upload", args=[self.order.pk]),
            {"document_type": RegistrationDocument.DocumentType.OTHER_INSURANCE, "name": "保單", "file": png()},
        )
        self.client.post(
            reverse("subsidy_document_upload", args=[self.order.pk]),
            {"document_type": "other", "name": "切結書", "file": png()},
        )
        self.client.post(reverse("order_attachment_upload", args=[self.order.pk]), {"files": png("a.png")})
        self.client.post(reverse("contract_upload", args=[self.order.pk]), {"signed_contract": png("contract.png")})
        self.client.post(reverse("privacy_consent_upload", args=[self.order.pk]), {"privacy_consent": png("consent.png")})
        self.assertEqual(RegistrationDocument.objects.filter(order=self.order).count(), 1)
        self.assertEqual(SubsidyDocument.objects.filter(order=self.order).count(), 1)
        self.assertEqual(self.order.other_attachments.count(), 1)
        self.assertEqual(self.versions(), before)
        self.assertTrue(self.order.signed_contract)
        self.assertTrue(self.order.privacy_consent)


class InplaceWholeFormTests(TestCase):
    """整張表單一起送出的頁面（列印範本、公告）：原地儲存，失敗只換表單區塊。"""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", "", "test-pass-123")
        self.client.force_login(self.admin)

    def test_print_template_form_saves_in_place(self):
        template = PositionedPrintTemplate.objects.create(name="範本", document_type=PositionedPrintTemplate._meta.get_field("document_type").choices[0][0])
        html = self.client.get(reverse("positioned_template_edit", args=[template.pk])).content.decode()
        self.assertRegex(html, r'<form [^>]*id="print-template-form" data-inplace-region data-inplace-form')
        self.assertIn('id="print-template-title" data-inplace-region', html)
        self.assertLess(html.index("js/inplace-regions.js"), html.index("js/positioned-template-fields.js"))

    def test_print_template_invalid_save_renders_same_url_without_success_message(self):
        # 前端以「同網址＋沒有成功訊息」判斷驗證失敗，只換表單並保留已選檔案。
        template = PositionedPrintTemplate.objects.create(name="範本", document_type=PositionedPrintTemplate._meta.get_field("document_type").choices[0][0])
        response = self.client.post(reverse("positioned_template_edit", args=[template.pk]), {"name": ""})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'class="message success"')
        self.assertContains(response, 'id="print-template-form"')

    def test_announcement_pages_mark_editor_and_list(self):
        html = self.client.get(reverse("announcement_manage")).content.decode()
        self.assertIn('id="announcement-editor" data-inplace-region', html)
        self.assertIn('id="announcement-list" data-inplace-region', html)
        self.assertIn('class="announcement-form" data-inplace-form', html)
        self.assertIn("js/inplace-regions.js", html)

    def test_catalog_edit_form_saves_in_place_and_keeps_success_message(self):
        model = VehicleModel.objects.create(brand="SUZUKI", name="SUI 125", energy_type=VehicleModel.EnergyType.GAS)
        VehicleColor.objects.create(vehicle_model=model, name="灰")
        url = reverse("catalog_edit", args=[model.pk])
        html = self.client.get(url).content.decode()
        self.assertIn('id="catalog-edit-form" data-inplace-region data-inplace-form', html)
        self.assertLess(html.index("js/inplace-regions.js"), html.index("js/catalog-image-preview.js"))
        # 存好導回同網址：前端以成功訊息判斷「已儲存」並換上新版 expected_revision。
        response = self.client.post(url, {"expected_revision": 0, "description": "通勤", "position": 0}, follow=True)
        self.assertEqual(response.request["PATH_INFO"], url)
        self.assertContains(response, 'class="message success"')
        self.assertContains(response, 'name="expected_revision" value="1"')
