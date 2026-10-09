"""admin 草稿清理：看得到所有人的草稿（不顯示客戶資料），填原因後刪除並留稽核紀錄。"""
from datetime import timedelta
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import OrderDraft, UserAccountAuditLog, VehicleModel

CUSTOMER = "王小明測試"


class DraftCleanupTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        override = override_settings(MEDIA_ROOT=self.temp.name)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(self.temp.cleanup)
        users = get_user_model()
        self.root = users.objects.create_superuser("admin", password="Test-Only-123")
        self.staff = users.objects.create_user("Sylvia", password="Test-Only-123")
        UserAccessState.objects.create(user=self.staff, configured=True)
        for key in ("orders", "order_intake"):
            ScreenAccessGrant.objects.create(user=self.staff, screen_key=key, view=True, operate=True)
        self.model = VehicleModel.objects.create(
            brand="SUZUKI", name="草稿車", model_number="DR125", model_year=2026,
            model_code=VehicleModel.ModelType.DRUM, energy_type=VehicleModel.EnergyType.GAS, displacement_cc=125)
        self.draft = OrderDraft.objects.create(
            owner_account=self.staff, created_by="Sylvia", updated_by="Sylvia",
            data={"_reception": True, "owner_name": CUSTOMER, "owner_phone": "0912000111", "vehicle_model": self.model.pk},
            id_front=SimpleUploadedFile("front.jpg", b"fake-image-bytes", content_type="image/jpeg"),
        )
        self.photo_path = self.draft.id_front.path

    def delete(self, **data):
        payload = {"reason": "建立人確認不再使用", "confirmed": "1"}
        payload.update(data)
        return self.client.post(reverse("draft_cleanup_delete", args=[self.draft.pk]), payload, follow=True)

    def test_admin_sees_everyones_drafts_without_customer_details(self):
        self.client.force_login(self.root)
        response = self.client.get(reverse("draft_cleanup_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sylvia")
        self.assertContains(response, "接待草稿")
        self.assertContains(response, str(self.model))
        self.assertNotContains(response, CUSTOMER)
        self.assertNotContains(response, "0912000111")
        self.assertContains(self.client.get(reverse("order_list")), reverse("draft_cleanup_list"))

    def test_other_staff_cannot_open_or_delete(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("draft_cleanup_list")).status_code, 403)
        response = self.client.post(reverse("draft_cleanup_delete", args=[self.draft.pk]),
                                    {"reason": "試圖刪除", "confirmed": "1"})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(OrderDraft.objects.filter(pk=self.draft.pk).exists())
        self.assertNotContains(self.client.get(reverse("order_list")), reverse("draft_cleanup_list"))

    def test_delete_needs_reason_and_confirmation(self):
        self.client.force_login(self.root)
        self.assertContains(self.delete(reason=""), "請填寫刪除原因")
        self.assertContains(self.delete(confirmed=""), "請勾選確認")
        self.assertTrue(OrderDraft.objects.filter(pk=self.draft.pk).exists())

    def test_delete_removes_draft_and_photo_and_writes_audit_log(self):
        from pathlib import Path
        self.assertTrue(Path(self.photo_path).exists())
        self.client.force_login(self.root)
        response = self.delete()
        self.assertContains(response, "已刪除草稿與暫存證件照片")
        self.assertFalse(OrderDraft.objects.filter(pk=self.draft.pk).exists())
        self.assertFalse(Path(self.photo_path).exists())
        log = UserAccountAuditLog.objects.get(actor=self.root, target=self.staff)
        self.assertEqual(log.action, UserAccountAuditLog.Action.DELETE_DRAFT)
        self.assertEqual(log.get_action_display(), "刪除草稿")
        self.assertIn("刪除接待草稿", log.description)
        self.assertIn("建立人確認不再使用", log.description)
        self.assertIn("有暫存證件照片", log.description)
        self.assertNotIn(CUSTOMER, log.description)
        # 原建立人的接待草稿清單也不再出現
        self.client.force_login(self.staff)
        self.assertNotContains(self.client.get(reverse("intake_drafts")), str(self.draft.pk))

    def test_cannot_delete_while_someone_else_is_editing(self):
        OrderDraft.objects.filter(pk=self.draft.pk).update(
            editing_session="someone-else", editing_by="Sylvia", editing_at=timezone.now())
        self.client.force_login(self.root)
        page = self.client.get(reverse("draft_cleanup_list"))
        self.assertContains(page, "Sylvia 編輯中，暫時不能刪除")
        self.assertContains(self.delete(), "Sylvia 正在編輯這份草稿")
        self.assertTrue(OrderDraft.objects.filter(pk=self.draft.pk).exists())
        # 心跳已逾時（離開頁面）就可以刪除
        OrderDraft.objects.filter(pk=self.draft.pk).update(editing_at=timezone.now() - timedelta(seconds=120))
        self.assertContains(self.delete(), "已刪除草稿")
        self.assertFalse(OrderDraft.objects.filter(pk=self.draft.pk).exists())

    def test_deleting_twice_reports_it_is_already_gone(self):
        self.client.force_login(self.root)
        self.delete()
        self.assertContains(self.delete(), "找不到這份草稿")
