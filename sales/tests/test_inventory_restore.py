"""車輛改回現有庫存（1.86.21，使用者 2026-10-19 選方案 B）。"""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import (SalesOrder, SalesSource, Store, VehicleColor, VehicleInventory, VehicleModel,
                          VehicleTransferSignoff)
from sales.services.inventory_history import change_rows
from sales.services.inventory_restore import identifier_tail, restore_blockers, restore_to_stock
from sales.services.order_deletion import change_deletion, confirmation_token


class InventoryRestoreTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = get_user_model().objects.create_superuser("admin", password="Restore-test-only-731!")
        cls.staff = get_user_model().objects.create_user("staff")
        UserAccessState.objects.create(user=cls.staff, configured=True)
        ScreenAccessGrant.objects.create(user=cls.staff, screen_key="inventory", view=True, operate=True)
        cls.model = VehicleModel.objects.create(brand="QA", name="回庫測試車", model_year=2026)
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="白")
        cls.store = Store.objects.create(name="合成門市")
        cls.dealer = SalesSource.objects.create(name="合成調出車行", source_type="dealer")

    def setUp(self):
        self.client.force_login(self.root)

    def vehicle(self, status, **extra):
        extra.setdefault("frame_number", f"QA-RESTORE-{VehicleInventory.objects.count()}")
        return VehicleInventory.objects.create(vehicle_model=self.model, color=self.color, ownership_store=self.store,
            location_store=self.store, status=status, **extra)

    def order(self, **extra):
        return SalesOrder.objects.create(owner_name="合成客戶", owner_phone="0900000000", owner_address="合成地址",
            owner_id_number="A123456789", vehicle_model=self.model, color=self.color, **extra)

    def restore(self, vehicle, **extra):
        vehicle.refresh_from_db()
        payload = dict(user=self.root, vehicle_id=vehicle.pk, reason="確認車在店內", expected_updated_at=vehicle.updated_at.isoformat())
        payload.update(extra)
        restored = restore_to_stock(**payload)
        vehicle.refresh_from_db()
        return restored

    def test_inactive_vehicle_returns_to_stock_with_audit(self):
        vehicle = self.vehicle("inactive")
        self.restore(vehicle, actor_name="管理員")
        self.assertEqual(vehicle.status, "available")
        history = vehicle.history_entries.get()
        self.assertEqual(history.actor_name, "管理員")
        self.assertEqual(history.reason, "改回現有庫存（原為停用）：確認車在店內")
        self.assertEqual(change_rows(history.changes), [{"label": "庫存狀態", "before": "停用", "after": "可銷售", "single": False}])

    def test_only_admin_and_reason_and_fresh_version(self):
        vehicle = self.vehicle("inactive")
        with self.assertRaises(PermissionDenied):
            restore_to_stock(user=self.staff, vehicle_id=vehicle.pk, reason="x", expected_updated_at=vehicle.updated_at.isoformat())
        with self.assertRaisesMessage(ValidationError, "備註最多 500 字"):
            self.restore(vehicle, reason="x" * 501)
        with self.assertRaisesMessage(ValidationError, "車輛資料已被更新"):
            self.restore(vehicle, expected_updated_at="2000-01-01T00:00:00+00:00")
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, "inactive")
        self.assertFalse(vehicle.history_entries.exists())
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("inventory_restore", args=[vehicle.pk])).status_code, 403)
        self.assertNotContains(self.client.get(reverse("inventory_edit", args=[vehicle.pk])), "改回現有庫存")

    def test_sold_and_delivered_require_identifier_tail_and_clear_disposition(self):
        vehicle = self.vehicle("sold", disposition="sold", disposition_dealer=self.dealer, disposition_on=timezone.localdate(),
                               frame_number="rfg-ab 1234x9")
        self.assertEqual(identifier_tail(vehicle), "34X9")
        for typed in ("", "1234", "34x8"):
            with self.assertRaisesMessage(ValidationError, "末 4 碼"):
                self.restore(vehicle, confirm_identifier=typed)
        self.restore(vehicle, confirm_identifier=" 34x9 ")
        self.assertEqual((vehicle.status, vehicle.disposition, vehicle.disposition_dealer_id, vehicle.disposition_on), ("available", "", None, None))
        rows = change_rows(vehicle.history_entries.get().changes)
        self.assertIn("去向", [row["label"] for row in rows])
        delivered = self.vehicle("delivered")
        with self.assertRaises(ValidationError):
            self.restore(delivered)
        self.restore(delivered, confirm_identifier=identifier_tail(delivered))
        self.assertEqual(delivered.status, "available")

    def test_reserved_and_transferred_out_without_links_return_to_stock(self):
        for status in ("reserved", "transferred_out"):
            vehicle = self.vehicle(status)
            self.restore(vehicle)
            self.assertEqual(vehicle.status, "available")

    def test_linked_order_blocks_and_points_to_order_flow(self):
        vehicle = self.vehicle("reserved")
        order = self.order(status=SalesOrder.Status.ALLOCATED, allocated_vehicle=vehicle)
        (text, url, _label), = restore_blockers(vehicle)
        self.assertIn(order.number, text)
        self.assertIn("取消、改配或例外結案", text)
        self.assertEqual(url, reverse("order_detail", args=[order.pk]))
        with self.assertRaisesMessage(ValidationError, order.number):
            self.restore(vehicle)
        SalesOrder.objects.filter(pk=order.pk).update(status=SalesOrder.Status.COMPLETED)
        VehicleInventory.objects.filter(pk=vehicle.pk).update(status="delivered")
        vehicle.refresh_from_db()
        self.assertIn("交車後退車", restore_blockers(vehicle)[0][0])
        page = self.client.get(reverse("inventory_restore", args=[vehicle.pk]))
        self.assertContains(page, "目前不能改回")
        self.assertNotContains(page, "確認改回現有庫存")
        self.assertEqual(self.client.post(reverse("inventory_restore", args=[vehicle.pk]), {
            "reason": "嘗試", "confirm_identifier": identifier_tail(vehicle), "expected_updated_at": vehicle.updated_at.isoformat()}).status_code, 200)
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, "delivered")

    def test_transfer_signoffs_block_until_handled_in_signoff_flow(self):
        vehicle = self.vehicle("transferred_out")
        signed = VehicleTransferSignoff.objects.create(dealer=self.dealer, dealer_name=self.dealer.name, staff_name="合成",
                                                       status=VehicleTransferSignoff.Status.SIGNED, signed_at=timezone.now())
        signed.vehicles.add(vehicle)
        self.assertIn("作廢調車簽收", restore_blockers(vehicle)[0][0])
        VehicleTransferSignoff.objects.filter(pk=signed.pk).update(voided_at=timezone.now())
        self.assertEqual(restore_blockers(vehicle), [])
        pending = VehicleTransferSignoff.objects.create(dealer=self.dealer, dealer_name=self.dealer.name, staff_name="合成",
                                                        status=VehicleTransferSignoff.Status.PENDING)
        pending.vehicles.add(vehicle)
        self.assertIn("請先取消預備調車", restore_blockers(vehicle)[0][0])

    def test_available_vehicle_has_nothing_to_restore(self):
        vehicle = self.vehicle("available")
        self.assertIn("不需要改回", restore_blockers(vehicle)[0][0])
        self.assertNotContains(self.client.get(reverse("inventory_edit", args=[vehicle.pk])), "改回現有庫存")

    def deleted_registered_vehicle(self):
        vehicle = self.vehicle("reserved")
        order = self.order(status=SalesOrder.Status.DELIVERY_PENDING, allocated_vehicle=vehicle, final_plate_number="QA-9988",
                           registration_completed_at=timezone.now(), registration_date=timezone.localdate())
        change_deletion(user=self.root, order_id=order.pk, restore=False, reason="重複匯入", force=True,
                        expected_updated_at=order.updated_at.isoformat(), confirmation=confirmation_token(order, self.root))
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, "inactive")
        return vehicle, order

    def test_deleted_registered_vehicle_requires_mode_choice(self):
        vehicle, order = self.deleted_registered_vehicle()
        with self.assertRaisesMessage(ValidationError, "請選擇要當新車還是已領牌車"):
            self.restore(vehicle)
        with self.assertRaisesMessage(ValidationError, "請填寫領牌車再售價"):
            self.restore(vehicle, mode="registered")
        self.restore(vehicle, mode="registered", resale_price="52000")
        self.assertEqual((vehicle.status, vehicle.registered_plate_number, vehicle.resale_price), ("available", "QA-9988", 52000))
        self.assertTrue(vehicle.is_registered_vehicle)
        rows = change_rows(vehicle.history_entries.order_by("-created_at", "-id").first().changes)
        self.assertTrue(any(f"刪單待確認已處理（刪除的訂單 {order.number}）" == row["after"] for row in rows))
        # 已改回的車，原訂單不能再直接還原（車輛已異動）。
        with self.assertRaisesMessage(ValidationError, "庫存車已異動"):
            change_deletion(user=self.root, order_id=order.pk, restore=True, reason="還原",
                            expected_updated_at=SalesOrder.all_objects.get(pk=order.pk).updated_at.isoformat())

    def test_deleted_registered_vehicle_can_return_as_new(self):
        vehicle, _order = self.deleted_registered_vehicle()
        self.restore(vehicle, mode="new")
        self.assertEqual((vehicle.status, vehicle.registered_plate_number, vehicle.resale_price), ("available", "", None))

    def test_detail_entry_confirm_page_and_list_flag(self):
        vehicle, order = self.deleted_registered_vehicle()
        detail = self.client.get(reverse("inventory_edit", args=[vehicle.pk]))
        self.assertContains(detail, "restore-entry is-review")
        self.assertContains(detail, f"刪除訂單 {order.number} 時已領牌")
        # 舊格式紀錄（無標籤、單值訂單）不再出現空白列或英文代碼。
        self.assertNotContains(detail, "reserved")
        self.assertContains(detail, '<div class="is-single"><strong>訂單</strong>')
        listing = self.client.get(reverse("inventory_list"), {"scope": "history"})
        self.assertContains(listing, "inventory-review-flag")
        self.assertContains(listing, reverse("inventory_restore", args=[vehicle.pk]))
        url = reverse("inventory_restore", args=[vehicle.pk])
        page = self.client.get(url)
        self.assertContains(page, "這台車有領牌紀錄")
        self.assertContains(page, "QA-9988")
        self.assertContains(page, 'name="mode"')
        vehicle.refresh_from_db()
        response = self.client.post(url, {"reason": "核對後確認可再售", "mode": "registered",
                                          "expected_updated_at": vehicle.updated_at.isoformat()})
        self.assertContains(response, "當已領牌車改回時，請填寫再售價")
        response = self.client.post(url, {"reason": "核對後確認可再售", "mode": "new",
                                          "expected_updated_at": vehicle.updated_at.isoformat()})
        self.assertRedirects(response, reverse("inventory_edit", args=[vehicle.pk]))
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, "available")
        self.assertNotContains(self.client.get(reverse("inventory_list"), {"scope": "history"}), "inventory-review-flag")

    def test_sold_vehicle_page_asks_for_identifier_tail(self):
        vehicle = self.vehicle("sold", frame_number="QA-VIEW-5678")
        url = reverse("inventory_restore", args=[vehicle.pk])
        page = self.client.get(url)
        self.assertContains(page, "二次確認")
        self.assertContains(page, 'name="confirm_identifier"')
        self.assertContains(page, "銷售台數、淨利與佣金以訂單計")
        payload = {"reason": "匯入誤標已售出", "expected_updated_at": vehicle.updated_at.isoformat(), "confirm_identifier": "1234"}
        self.assertContains(self.client.post(url, payload), "號碼不符")
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, "sold")
        payload["confirm_identifier"] = "5678"
        self.assertRedirects(self.client.post(url, payload), reverse("inventory_edit", args=[vehicle.pk]))
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, "available")

    def test_legacy_history_rows_render_labels(self):
        rows = change_rows({"order": "SO1", "status": {"before": "reserved", "after": "inactive"},
                            "庫存狀態": {"before": "available", "after": "reserved"}, "訂單": "SO2"})
        self.assertEqual(rows, [
            {"label": "庫存狀態", "before": "已預留", "after": "停用", "single": False},
            {"label": "庫存狀態", "before": "可銷售", "after": "已預留", "single": False},
            {"label": "訂單", "before": "", "after": "SO1", "single": True},
            {"label": "訂單", "before": "", "after": "SO2", "single": True},
        ])
