"""調出（T-310，原 1.62.0 調車簽收）：庫存列表勾車 → 調給哪一家 → 確認，不簽名、不產生 PDF、沒有預備調車。

調出後改為已調出（不算庫存），留一筆調車紀錄；admin 可作廢。2026-11-24 以前已簽名的舊紀錄照常顯示簽名與 PDF。
"""
from datetime import date
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.signals import request_finished
from django.db import close_old_connections
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.access.registry import ROOT_ONLY, ROUTES
from sales.models import (
    SalesSource,
    Store,
    VehicleColor,
    VehicleInventory,
    VehicleModel,
    VehicleTransferSignoff,
)
from sales.services.transfer_signoff import name_suggestions

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


class TransferSignoffTests(TestCase):
    def setUp(self):
        self.tempdir = TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.tempdir.name)
        self.override.enable()
        self.store = Store.objects.create(name="總店", code="MAIN")
        self.root = get_user_model().objects.create_superuser("admin", password="Local-transfer-984!")
        self.client.force_login(self.root)
        self.dealer = SalesSource.objects.create(name="示範車行甲", source_type=SalesSource.SourceType.DEALER, active=True)
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

    def transfer_out(self, cars, name="示範車行甲", note="含鑰匙", ajax=False, **extra):
        data = {
            "vehicles": [car.pk for car in cars], "name": name, "note": note,
            "next": f"{reverse('inventory_list')}?scope=current", **extra,
        }
        return self.client.post(reverse("inventory_transfer_out"), data, **(AJAX if ajax else {}))

    def test_transfer_out_several_cars_without_signature(self):
        cars = self.cars[:3]
        response = self.transfer_out(cars)
        signoff = VehicleTransferSignoff.objects.get()
        self.assertRedirects(response, f"{reverse('inventory_list')}?scope=current", fetch_redirect_response=False)
        self.assertEqual(signoff.status, VehicleTransferSignoff.Status.SIGNED)
        self.assertEqual(signoff.dealer, self.dealer)
        self.assertEqual(signoff.dealer_name, "示範車行甲")
        self.assertEqual(len(signoff.vehicles_snapshot), 3)
        self.assertEqual(signoff.vehicles.count(), 3)
        self.assertFalse(signoff.signed_pdf)
        self.assertFalse(signoff.signature_image)
        self.assertEqual(signoff.pdf_sha256, "")
        self.assertEqual(signoff.fingerprint, "")
        for car in cars:
            car.refresh_from_db()
            self.assertEqual(car.status, VehicleInventory.Status.TRANSFERRED_OUT)
            self.assertEqual(car.disposition, VehicleInventory.Disposition.TRANSFER_OUT)
            self.assertEqual(car.disposition_dealer, self.dealer)
            self.assertIsNotNone(car.disposition_on)
            self.assertIn(signoff.number, car.history_entries.get().reason)

        detail = self.client.get(reverse("transfer_signoff_detail", args=[signoff.pk]))
        self.assertContains(detail, "調往 示範車行甲")
        self.assertContains(detail, "含鑰匙")
        self.assertNotContains(detail, "領車人簽名")
        self.assertNotContains(detail, "開啟簽收單 PDF")
        self.assertEqual(self.client.get(reverse("transfer_signoff_pdf", args=[signoff.pk])).status_code, 404)
        # 回到列表：底部提示「已調出 N 台給 X｜看調車紀錄」只出現一次；已調出的車不在現有庫存，列在「已售出／調出」。
        listing = self.client.get(reverse("inventory_list"))
        self.assertContains(listing, "已調出 3 台給 示範車行甲")
        self.assertContains(listing, reverse("transfer_signoff_detail", args=[signoff.pk]))
        self.assertNotIn(cars[0], list(listing.context["vehicles"]))
        self.assertNotContains(self.client.get(reverse("inventory_list")), "已調出 3 台給")
        self.assertIn(cars[0], list(self.client.get(reverse("inventory_list"), {"scope": "sold"}).context["vehicles"]))

    def test_ajax_reply_carries_redirect_back_to_the_same_list(self):
        response = self.transfer_out(self.cars[:1], ajax=True, next="/data/inventory/?scope=current&page=2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["redirect"], "/data/inventory/?scope=current&page=2")
        self.assertTrue(response.json()["ok"])
        outside = self.transfer_out(self.cars[1:2], ajax=True, next="https://evil.example/")
        self.assertEqual(outside.json()["redirect"], f"{reverse('inventory_list')}?scope=current")

    def test_dealer_not_in_master_uses_typed_name(self):
        cars = self.cars[:1]
        self.transfer_out(cars, name="示範車行丙")
        signoff = VehicleTransferSignoff.objects.get()
        self.assertIsNone(signoff.dealer)
        self.assertEqual(signoff.dealer_name, "示範車行丙")
        cars[0].refresh_from_db()
        self.assertEqual(cars[0].disposition_dealer_name, "示範車行丙")

    def test_typed_name_equal_to_active_dealer_links_master(self):
        SalesSource.objects.create(name="停用車行", source_type=SalesSource.SourceType.DEALER, active=False)
        self.transfer_out(self.cars[:1], name="  示範車行甲 ")
        self.transfer_out(self.cars[1:2], name="停用車行")
        first, second = VehicleTransferSignoff.objects.order_by("id")
        self.assertEqual((first.dealer, first.dealer_name), (self.dealer, "示範車行甲"))
        self.assertEqual((second.dealer, second.dealer_name), (None, "停用車行"), "停用車行不連主檔，只存原文")

    def test_factory_recall_option(self):
        cars = self.cars[:2]
        self.transfer_out(cars, name="原廠／總公司（調回）")
        signoff = VehicleTransferSignoff.objects.get()
        self.assertIsNone(signoff.dealer)
        self.assertEqual(signoff.dealer_name, "原廠／總公司")
        cars[0].refresh_from_db()
        self.assertEqual(cars[0].status, VehicleInventory.Status.TRANSFERRED_OUT)
        self.assertEqual(cars[0].disposition_dealer_name, "原廠／總公司")

    def test_reserved_car_cannot_be_transferred(self):
        response = self.transfer_out(self.cars[2:], ajax=True)
        self.assertEqual(response.status_code, 400)
        self.assertIn("不能調出", response.json()["message"])
        self.assertFalse(VehicleTransferSignoff.objects.exists())
        self.assertEqual(VehicleInventory.objects.get(pk=self.cars[2].pk).status, "condition_issue", "整批不調")

    def test_car_allocated_after_dialog_opened_blocks_whole_batch(self):
        cars = self.cars[:2]
        self.assertEqual(self.client.get(reverse("inventory_list")).status_code, 200)
        VehicleInventory.objects.filter(pk=cars[0].pk).update(status="reserved")
        response = self.transfer_out(cars, ajax=True)
        self.assertEqual(response.status_code, 400)
        self.assertIn(cars[0].identifier, response.json()["message"])
        self.assertFalse(VehicleTransferSignoff.objects.exists())
        self.assertEqual(VehicleInventory.objects.get(pk=cars[1].pk).status, "available")

    def test_no_signature_or_agreement_needed(self):
        cars = self.cars[:1]
        response = self.transfer_out(cars, ajax=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(VehicleTransferSignoff.objects.count(), 1)
        cars[0].refresh_from_db()
        self.assertEqual(cars[0].status, VehicleInventory.Status.TRANSFERRED_OUT)

    def test_name_is_required(self):
        response = self.transfer_out(self.cars[:1], name="  ", ajax=True)
        self.assertEqual(response.status_code, 400)
        self.assertIn("調給哪一家", response.json()["message"])
        self.assertFalse(VehicleTransferSignoff.objects.exists())

    def test_home_store_names_are_blocked_and_point_to_actual_location(self):
        for name in ("本店", "本店：馭盛", "馭盛", " 永 湛 "):
            response = self.transfer_out(self.cars[:1], name=name, ajax=True)
            self.assertEqual(response.status_code, 400, name)
            self.assertIn("實際位置", response.json()["message"])
        self.assertFalse(VehicleTransferSignoff.objects.exists())
        self.assertEqual(VehicleInventory.objects.get(pk=self.cars[0].pk).status, "available")

    def test_transferred_or_sold_cars_and_resubmits_are_rejected(self):
        self.transfer_out(self.cars[:1])
        again = self.transfer_out(self.cars[:1], ajax=True)
        self.assertEqual(again.status_code, 400, "同一請求重送時車已調出，不會重複調出")
        self.assertEqual(VehicleTransferSignoff.objects.count(), 1)
        VehicleInventory.objects.filter(pk=self.cars[1].pk).update(status="sold")
        self.assertEqual(self.transfer_out(self.cars[1:2], ajax=True).status_code, 400)
        self.assertEqual(self.transfer_out([], ajax=True).status_code, 400)

    def test_transfer_out_keeps_actual_location_fields(self):
        car = self.cars[0]
        VehicleInventory.objects.filter(pk=car.pk).update(current_dealer=self.dealer)
        self.transfer_out([car], name="示範車行丙")
        car.refresh_from_db()
        self.assertEqual(car.current_dealer, self.dealer)
        self.assertEqual(car.location_store, self.store)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(reverse("inventory_transfer_out")).status_code, 405)

    def test_old_create_url_redirects_to_inventory_list(self):
        response = self.client.get(reverse("transfer_signoff_create"))
        self.assertRedirects(response, f"{reverse('inventory_list')}?scope=current")

    def test_old_signed_record_still_shows_signature_and_pdf(self):
        signoff = VehicleTransferSignoff.objects.create(
            dealer=self.dealer, dealer_name=self.dealer.name, staff_name="合成", signed_at=timezone.now(),
            vehicles_snapshot=[], fingerprint="a" * 64, pdf_sha256="b" * 64,
        )
        signoff.signature_image.save("old-signature.png", ContentFile(b"\x89PNG\r\n\x1a\n"), save=False)
        signoff.signed_pdf.save("old.pdf", ContentFile(b"%PDF-1.4 old"), save=False)
        signoff.save()
        detail = self.client.get(reverse("transfer_signoff_detail", args=[signoff.pk]))
        self.assertContains(detail, "領車人簽名")
        self.assertContains(detail, "開啟簽收單 PDF")
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

    def test_void_restores_previous_status_and_keeps_record(self):
        cars = self.cars[:3]
        self.transfer_out(cars)
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
        self.transfer_out([car])
        first = VehicleTransferSignoff.objects.get()
        self.client.post(reverse("transfer_signoff_void", args=[first.pk]), {"reason": "先作廢"})
        self.transfer_out([car])
        second = VehicleTransferSignoff.objects.exclude(pk=first.pk).get()
        self.assertEqual(VehicleInventory.objects.get(pk=car.pk).status, VehicleInventory.Status.TRANSFERRED_OUT)
        self.assertNotEqual(first, second)

    def test_routes_are_registered_and_void_is_admin_only(self):
        self.assertIn("transfer_signoff_void", ROOT_ONLY)
        self.assertEqual(ROUTES["transfer_signoff_create"], ("inventory", "operate"))
        self.assertEqual(ROUTES["inventory_transfer_out"], ("inventory", "operate"))
        self.assertNotIn("transfer_signoff_cancel", ROUTES)
        self.assertEqual(ROUTES["transfer_signoff_list"][0], "inventory")
        staff = get_user_model().objects.create_user("staff", password="Local-staff-984!")
        self.client.force_login(staff)
        response = self.client.post(reverse("transfer_signoff_void", args=[1]), {"reason": "x"})
        self.assertIn(response.status_code, {302, 403, 404})
        self.assertFalse(VehicleTransferSignoff.objects.filter(voided_at__isnull=False).exists())


class TransferPendingAndRecordsTests(TransferSignoffTests):
    """1.66.0：調車紀錄篩選、進車紀錄；T-310 起沒有預備調車，舊的待簽收資料不列在調車紀錄。"""

    def test_records_list_only_signed_and_filters_by_date(self):
        pending = VehicleTransferSignoff.objects.create(
            dealer=self.dealer, dealer_name=self.dealer.name, staff_name="合成", status=VehicleTransferSignoff.Status.PENDING,
        )
        pending.vehicles.add(self.cars[1])
        self.transfer_out(self.cars[:1])
        records = self.client.get(reverse("transfer_signoff_list"))
        self.assertEqual(len(records.context["signoffs"]), 1, "預備調車不列在調車紀錄")
        empty = self.client.get(reverse("transfer_signoff_list"), {"from": "2000-01-01", "to": "2000-01-02"})
        self.assertEqual(len(empty.context["signoffs"]), 0)

    def test_receipt_records_filter_by_date(self):
        VehicleInventory.objects.filter(pk=self.cars[0].pk).update(received_on=date(2026, 9, 1))
        VehicleInventory.objects.filter(pk__in=[c.pk for c in self.cars[1:]]).update(received_on=date(2026, 9, 5))
        response = self.client.get(reverse("inventory_receipt_list"), {"from": "2026-09-05", "to": "2026-09-05"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].paginator.count, 3)
        self.assertContains(response, "09/05")

    def test_inventory_list_offers_checkboxes_and_transfer_out_buttons(self):
        page = self.client.get(reverse("inventory_list"))
        html = page.content.decode()
        self.assertNotIn(reverse("transfer_signoff_create"), html, "標題列不再有「調車簽收」按鈕")
        self.assertIn(reverse("transfer_signoff_list"), html)
        self.assertIn("data-transfer-out-all", html)
        for car in self.cars[:3]:
            self.assertIn(f'data-transfer-out-one="{car.pk}"', html)
            self.assertIn(f'value="{car.pk}" aria-label="選 {car.identifier} 調出"', html)
        reserved = self.cars[3]
        self.assertNotIn(f'data-transfer-out-one="{reserved.pk}"', html)
        self.assertIn(f"{reserved.identifier} 已配給訂單，不能調出", html)
        self.assertIn(">已配車</button>", html)
        self.assertIn('id="transfer-out-names"', html)
        self.assertIn(reverse("inventory_transfer_out"), html)
        self.assertNotIn("領車人", html)
        # 停用、已售出／調出分頁沒有勾選與調出。
        for scope in ("history", "sold"):
            other = self.client.get(reverse("inventory_list"), {"scope": scope}).content.decode()
            self.assertNotIn("data-transfer-out", other)

    def test_name_suggestions_merge_used_names_and_dealers_without_home_stores(self):
        SalesSource.objects.create(name="示範車行乙", source_type=SalesSource.SourceType.DEALER)
        SalesSource.objects.create(name="永湛", source_type=SalesSource.SourceType.DEALER)
        SalesSource.objects.create(name="停用車行", source_type=SalesSource.SourceType.DEALER, active=False)
        VehicleInventory.objects.filter(pk=self.cars[0].pk).update(
            status="transferred_out", disposition="transfer_out", disposition_dealer_name="興隆機車行",
            disposition_on=date(2026, 3, 1),
        )
        VehicleInventory.objects.filter(pk=self.cars[1].pk).update(
            status="transferred_out", disposition="transfer_out", disposition_dealer_name="示範車行甲",
            disposition_on=date(2026, 5, 1),
        )
        VehicleInventory.objects.filter(pk=self.cars[2].pk).update(
            status="sold", disposition="sold", disposition_dealer_name="馭盛", disposition_on=date(2026, 6, 1),
        )
        names = name_suggestions()
        self.assertEqual(names["factory"], "原廠／總公司（調回）")
        self.assertEqual([item["name"] for item in names["used"]], ["示範車行甲", "興隆機車行"], "最近用過的在前、不含本店")
        self.assertIn("1 台", names["used"][0]["meta"])
        self.assertEqual(names["dealers"], ["示範車行乙"], "打過的不重複、不含本店與停用車行")
        self.assertEqual(names["home"], ["馭盛", "永湛"])


class TransferOutPermissionTests(TestCase):
    def setUp(self):
        store = Store.objects.create(name="總店", code="MAIN")
        model = VehicleModel.objects.create(brand="SYM", name="JET SL 125", model_number="T310P")
        color = VehicleColor.objects.create(vehicle_model=model, name="消光黑")
        self.car = VehicleInventory.objects.create(
            vehicle_model=model, color=color, frame_number="T310P0001", ownership_store=store, location_store=store,
        )
        self.user = get_user_model().objects.create_user("viewer", password="Local-t310-553!")
        UserAccessState.objects.create(user=self.user, configured=True)
        self.grant = ScreenAccessGrant.objects.create(user=self.user, screen_key="inventory", view=True)
        self.client.force_login(self.user)

    def post(self):
        return self.client.post(
            reverse("inventory_transfer_out"), {"vehicles": [self.car.pk], "name": "示範車行丙"}, **AJAX,
        )

    def test_view_only_user_gets_403_and_sees_no_checkboxes(self):
        self.assertEqual(self.post().status_code, 403)
        self.assertEqual(VehicleInventory.objects.get(pk=self.car.pk).status, "available")
        html = self.client.get(reverse("inventory_list")).content.decode()
        self.assertNotIn("data-transfer-out", html)
        self.assertNotIn("transfer-out-names", html)

    def test_operate_user_can_transfer_out(self):
        self.grant.operate = True
        self.grant.save()
        self.assertIn("data-transfer-out-all", self.client.get(reverse("inventory_list")).content.decode())
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(VehicleInventory.objects.get(pk=self.car.pk).status, "transferred_out")
