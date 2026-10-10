"""1.62.0：調車簽收（同一車行多台簽一次、只在店內簽署、簽後改為已調出、admin 可作廢）。"""
import base64
from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.signals import request_finished
from django.db import close_old_connections
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image, ImageDraw

from sales.access.registry import ROOT_ONLY, ROUTES
from sales.models import (
    SalesSource,
    Store,
    VehicleColor,
    VehicleInventory,
    VehicleModel,
    VehicleTransferSignoff,
)


def signature_data_url():
    image = Image.new("RGBA", (600, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.line([(30, 150), (200, 40), (380, 160), (560, 50)], fill=(0, 0, 0, 255), width=6)
    output = BytesIO()
    image.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()


class TransferSignoffTests(TestCase):
    def setUp(self):
        self.tempdir = TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.tempdir.name)
        self.override.enable()
        self.store = Store.objects.create(name="總店", code="MAIN")
        self.root = get_user_model().objects.create_superuser("admin", password="Local-transfer-984!")
        self.client.force_login(self.root)
        self.dealer = SalesSource.objects.create(name="昌勝", source_type=SalesSource.SourceType.DEALER, active=True)
        model = VehicleModel.objects.create(brand="SYM", name="JET SL 125", model_number="TEST125")
        color = VehicleColor.objects.create(vehicle_model=model, name="消光黑")
        self.cars = [
            VehicleInventory.objects.create(
                vehicle_model=model, color=color, frame_number=f"RFG{n:05d}",
                ownership_store=self.store, location_store=self.store, status=status,
            )
            for n, status in enumerate(("available", "available", "condition_issue", "reserved"))
        ]

    def tearDown(self):
        self.override.disable()
        self.tempdir.cleanup()

    def form(self, cars, **extra):
        data = {
            "dealer": self.dealer.pk, "dealer_name": "", "note": "含鑰匙", "vehicles": [car.pk for car in cars],
        }
        data.update(extra)
        return data

    def review(self, cars, **extra):
        response = self.client.post(reverse("transfer_signoff_create"), {**self.form(cars, **extra), "step": "review"})
        self.assertEqual(response.status_code, 200, response.context and response.context["errors"])
        self.assertEqual(response.context["step"], "sign")
        return response.context["fingerprint"]

    def sign(self, cars, fingerprint, **extra):
        payload = {**self.form(cars), "step": "sign", "agree": "1", "fingerprint": fingerprint,
                   "signature": signature_data_url(), **extra}
        return self.client.post(reverse("transfer_signoff_create"), payload)

    def test_one_signature_for_several_cars_marks_them_transferred_out(self):
        cars = self.cars[:3]
        response = self.sign(cars, self.review(cars))
        signoff = VehicleTransferSignoff.objects.get()
        self.assertRedirects(response, reverse("transfer_signoff_detail", args=[signoff.pk]))
        self.assertEqual(signoff.dealer, self.dealer)
        self.assertEqual(signoff.dealer_name, "昌勝")
        self.assertEqual(len(signoff.vehicles_snapshot), 3)
        self.assertEqual(signoff.vehicles.count(), 3)
        self.assertTrue(signoff.signed_pdf.name.endswith(".pdf"))
        self.assertTrue(signoff.signature_image.name.endswith(".png"))
        self.assertEqual(len(signoff.pdf_sha256), 64)
        for car in cars:
            car.refresh_from_db()
            self.assertEqual(car.status, VehicleInventory.Status.TRANSFERRED_OUT)
            self.assertEqual(car.disposition, VehicleInventory.Disposition.TRANSFER_OUT)
            self.assertEqual(car.disposition_dealer, self.dealer)
            self.assertIsNotNone(car.disposition_on)
            self.assertIn(signoff.number, car.history_entries.get().reason)

        detail = self.client.get(reverse("transfer_signoff_detail", args=[signoff.pk]))
        self.assertContains(detail, "調往 昌勝")
        self.assertContains(detail, "含鑰匙")
        pdf = self.client.get(reverse("transfer_signoff_pdf", args=[signoff.pk]))
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(b"".join(pdf.streaming_content).startswith(b"%PDF"))
        self.assertIn("no-store", pdf["Cache-Control"])
        image = self.client.get(reverse("protected_media", args=["transfer_signoff", signoff.pk, "signature_image"]))
        self.assertEqual(image.status_code, 200)
        # 關檔避免 Windows 檔案鎖；response.close() 會觸發 request_finished 關掉資料庫連線（PostgreSQL 上後續查詢失敗），所以暫時解除。
        request_finished.disconnect(close_old_connections)
        try:
            image.close()
        finally:
            request_finished.connect(close_old_connections)
        # 已調出的車不在現有庫存，列在「已售出／調出」。
        self.assertNotIn(cars[0], list(self.client.get(reverse("inventory_list")).context["vehicles"]))
        self.assertIn(cars[0], list(self.client.get(reverse("inventory_list"), {"scope": "sold"}).context["vehicles"]))

    def test_dealer_not_in_master_uses_typed_name(self):
        cars = self.cars[:1]
        fingerprint = self.review(cars, dealer="", dealer_name="榮擎")
        self.sign(cars, fingerprint, dealer="", dealer_name="榮擎")
        signoff = VehicleTransferSignoff.objects.get()
        self.assertIsNone(signoff.dealer)
        self.assertEqual(signoff.dealer_name, "榮擎")
        cars[0].refresh_from_db()
        self.assertEqual(cars[0].disposition_dealer_name, "榮擎")

    def test_factory_recall_option(self):
        cars = self.cars[:2]
        fingerprint = self.review(cars, dealer="factory", dealer_name="")
        response = self.client.post(reverse("transfer_signoff_create"), {**self.form(cars, dealer="factory", dealer_name=""), "step": "review"})
        self.assertContains(response, "調回 <span>原廠／總公司</span>", html=False)
        self.sign(cars, fingerprint, dealer="factory", dealer_name="")
        signoff = VehicleTransferSignoff.objects.get()
        self.assertIsNone(signoff.dealer)
        self.assertEqual(signoff.dealer_name, "原廠／總公司")
        cars[0].refresh_from_db()
        self.assertEqual(cars[0].status, VehicleInventory.Status.TRANSFERRED_OUT)
        self.assertEqual(cars[0].disposition_dealer_name, "原廠／總公司")

    def test_reserved_car_cannot_be_transferred(self):
        response = self.client.post(reverse("transfer_signoff_create"), {**self.form(self.cars[2:]), "step": "review"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.context["step"], "select")
        self.assertIn("不能調出", "".join(response.context["errors"]))

    def test_changed_content_after_review_requires_new_confirmation(self):
        cars = self.cars[:2]
        fingerprint = self.review(cars)
        response = self.sign(cars, fingerprint, note="改過的備註")
        self.assertEqual(response.status_code, 400)
        self.assertIn("剛被修改", "".join(response.context["errors"]))
        self.assertFalse(VehicleTransferSignoff.objects.exists())

    def test_signature_and_agreement_required(self):
        cars = self.cars[:1]
        fingerprint = self.review(cars)
        response = self.sign(cars, fingerprint, agree="")
        self.assertEqual(response.status_code, 400)
        response = self.sign(cars, fingerprint, signature="")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(VehicleTransferSignoff.objects.exists())
        cars[0].refresh_from_db()
        self.assertEqual(cars[0].status, VehicleInventory.Status.AVAILABLE)

    def test_void_restores_previous_status_and_keeps_record(self):
        cars = self.cars[:3]
        self.sign(cars, self.review(cars))
        signoff = VehicleTransferSignoff.objects.get()
        response = self.client.post(reverse("transfer_signoff_void", args=[signoff.pk]), {"reason": "選錯車"})
        self.assertRedirects(response, reverse("transfer_signoff_detail", args=[signoff.pk]))
        signoff.refresh_from_db()
        self.assertTrue(signoff.is_voided)
        self.assertEqual(signoff.void_reason, "選錯車")
        statuses = [VehicleInventory.objects.get(pk=car.pk).status for car in cars]
        self.assertEqual(statuses, ["available", "available", "condition_issue"])
        self.assertEqual(VehicleInventory.objects.get(pk=cars[0].pk).disposition, "")
        # 再作廢一次不會重複動到車輛。
        self.client.post(reverse("transfer_signoff_void", args=[signoff.pk]), {"reason": "重複"})
        signoff.refresh_from_db()
        self.assertEqual(signoff.void_reason, "選錯車")

    def test_void_skips_cars_transferred_again_later(self):
        car = self.cars[0]
        self.sign([car], self.review([car]))
        first = VehicleTransferSignoff.objects.get()
        self.client.post(reverse("transfer_signoff_void", args=[first.pk]), {"reason": "先作廢"})
        self.sign([car], self.review([car]))
        second = VehicleTransferSignoff.objects.exclude(pk=first.pk).get()
        self.assertEqual(VehicleInventory.objects.get(pk=car.pk).status, VehicleInventory.Status.TRANSFERRED_OUT)
        self.assertNotEqual(first, second)

    def test_routes_are_registered_and_void_is_admin_only(self):
        self.assertIn("transfer_signoff_void", ROOT_ONLY)
        self.assertEqual(ROUTES["transfer_signoff_create"], ("inventory", "operate"))
        self.assertEqual(ROUTES["transfer_signoff_list"][0], "inventory")
        staff = get_user_model().objects.create_user("staff", password="Local-staff-984!")
        self.client.force_login(staff)
        response = self.client.post(reverse("transfer_signoff_void", args=[1]), {"reason": "x"})
        self.assertIn(response.status_code, {302, 403, 404})
        self.assertFalse(VehicleTransferSignoff.objects.filter(voided_at__isnull=False).exists())

    def test_sign_step_hides_navigation_and_offers_no_external_link(self):
        cars = self.cars[:1]
        response = self.client.post(reverse("transfer_signoff_create"), {**self.form(cars), "step": "review"})
        self.assertContains(response, "signing-page")
        self.assertContains(response, 'data-signature-skip')
        # 簽名腳本送出時會停用確認按鈕（按鈕值不會送出），步驟必須放在隱藏欄位。
        self.assertContains(response, '<input type="hidden" name="step" value="sign">')
        self.assertNotContains(response, 'name="step" value="sign" data-signature-submit')

    def test_back_button_value_overrides_hidden_sign_step(self):
        cars = self.cars[:1]
        payload = {**self.form(cars), "fingerprint": self.review(cars)}
        response = self.client.post(reverse("transfer_signoff_create") , {**payload, "step": ["sign", "edit"]})
        self.assertEqual(response.context["step"], "select")
        self.assertFalse(VehicleTransferSignoff.objects.exists())


class TransferPendingAndRecordsTests(TransferSignoffTests):
    """1.66.0：預備調車（先存、等人來再簽）、調車紀錄篩選、進車紀錄。"""

    def test_prepare_then_sign_later(self):
        cars = self.cars[:2]
        response = self.client.post(reverse("transfer_signoff_create"), {**self.form(cars), "step": "save"})
        self.assertRedirects(response, reverse("transfer_signoff_create"))
        pending = VehicleTransferSignoff.objects.get()
        self.assertEqual(pending.status, VehicleTransferSignoff.Status.PENDING)
        self.assertEqual(VehicleInventory.objects.get(pk=cars[0].pk).status, "available", "預備時車輛不異動")
        page = self.client.get(reverse("transfer_signoff_create"))
        self.assertContains(page, "預備調車・待簽收")
        self.assertContains(page, "開始簽收")
        start = self.client.get(reverse("transfer_signoff_create"), {"pending": pending.pk, "sign": "1"})
        self.assertEqual(start.context["step"], "sign")
        fingerprint = start.context["fingerprint"]
        response = self.sign(cars, fingerprint, pending=pending.pk)
        self.assertRedirects(response, reverse("transfer_signoff_detail", args=[pending.pk]))
        pending.refresh_from_db()
        self.assertEqual(pending.status, VehicleTransferSignoff.Status.SIGNED)
        self.assertEqual(VehicleTransferSignoff.objects.count(), 1, "簽收沿用同一筆預備，不另建")
        self.assertEqual(VehicleInventory.objects.get(pk=cars[0].pk).status, "transferred_out")

    def test_prepared_car_allocated_meanwhile_cannot_be_signed(self):
        cars = self.cars[:2]
        self.client.post(reverse("transfer_signoff_create"), {**self.form(cars), "step": "save"})
        pending = VehicleTransferSignoff.objects.get()
        VehicleInventory.objects.filter(pk=cars[0].pk).update(status="reserved")
        start = self.client.get(reverse("transfer_signoff_create"), {"pending": pending.pk, "sign": "1"})
        self.assertEqual(start.context["step"], "select")
        self.assertIn("不能調出", "".join(start.context["errors"]))

    def test_cancel_pending_removes_it(self):
        self.client.post(reverse("transfer_signoff_create"), {**self.form(self.cars[:1]), "step": "save"})
        pending = VehicleTransferSignoff.objects.get()
        self.client.post(reverse("transfer_signoff_cancel", args=[pending.pk]))
        self.assertFalse(VehicleTransferSignoff.objects.exists())

    def test_records_list_only_signed_and_filters_by_date(self):
        self.client.post(reverse("transfer_signoff_create"), {**self.form(self.cars[1:2]), "step": "save"})
        self.sign(self.cars[:1], self.review(self.cars[:1]))
        records = self.client.get(reverse("transfer_signoff_list"))
        self.assertEqual(len(records.context["signoffs"]), 1, "預備調車不列在調車紀錄")
        empty = self.client.get(reverse("transfer_signoff_list"), {"from": "2000-01-01", "to": "2000-01-02"})
        self.assertEqual(len(empty.context["signoffs"]), 0)

    def test_receipt_records_filter_by_date(self):
        from datetime import date
        VehicleInventory.objects.filter(pk=self.cars[0].pk).update(received_on=date(2026, 9, 1))
        VehicleInventory.objects.filter(pk__in=[c.pk for c in self.cars[1:]]).update(received_on=date(2026, 9, 5))
        response = self.client.get(reverse("inventory_receipt_list"), {"from": "2026-09-05", "to": "2026-09-05"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].paginator.count, 3)
        self.assertContains(response, "09/05")

    def test_vehicle_cards_show_factory_month_and_filters(self):
        VehicleInventory.objects.filter(pk=self.cars[0].pk).update(manufactured_year_month="2026/06")
        page = self.client.get(reverse("transfer_signoff_create"))
        self.assertContains(page, "出廠 2026/06")
        self.assertContains(page, 'data-transfer-filter="model"')
        self.assertNotContains(page, "領車人姓名")
