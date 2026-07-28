import io
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from sales.models import OrderDraft, SalesOrder, VehicleColor, VehicleModel


class OrderDraftTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="draft-user", password="test-pass-123"
        )
        self.client.force_login(self.user)
        self.model = VehicleModel.objects.create(
            brand="測試", name="125", energy_type=VehicleModel.EnergyType.GAS
        )
        self.color = VehicleColor.objects.create(
            vehicle_model=self.model, name="白"
        )

    def image(self, name):
        content = io.BytesIO()
        Image.new("RGB", (4, 4), "white").save(content, format="PNG")
        return SimpleUploadedFile(
            name, content.getvalue(), content_type="image/png"
        )

    def complete_data(self):
        return {
            "source_type": "store",
            "source": "",
            "owner_type": "local",
            "owner_name": "測試車主",
            "owner_name_en": "",
            "owner_phone": "0912345678",
            "owner_email": "",
            "owner_birth_date": "1990-01-01",
            "owner_nationality": "",
            "owner_address": "測試地址",
            "owner_id_number": "A123456789",
            "residence_expiry": "",
            "id_verified": "on",
            "vehicle_model": str(self.model.pk),
            "color": str(self.color.pk),
            "payment_type": "cash",
            "vehicle_price": "79800",
            "plate_insurance_fee": "0",
            "installment_opening_fee": "0",
            "other_fee": "0",
            "discount_amount": "0",
            "deposit_amount": "0",
            "deposit_date": "",
            "deposit_method": "",
            "installment_company": "",
            "installment_amount": "0",
            "installment_periods": "0",
            "installment_monthly": "0",
            "installment_applied_on": "",
            "installment_status": "",
            "installment_decided_on": "",
            "trade_in_plate": "",
            "subsidy_type": "",
            "old_vehicle_valuation": "0",
            "old_vehicle_tax": "0",
            "plate_choice": "none",
            "watched_numbers": "",
            "plate_preference_note": "",
            "delivery_method": "",
            "note": "",
            "accessories-TOTAL_FORMS": "1",
            "accessories-INITIAL_FORMS": "0",
            "accessories-MIN_NUM_FORMS": "0",
            "accessories-MAX_NUM_FORMS": "1000",
            "accessories-0-name": "",
            "accessories-0-quantity": "1",
            "accessories-0-line_type": "purchase",
            "accessories-0-amount": "0",
            "accessories-0-installed_on": "",
            "accessories-0-note": "",
        }

    def test_autosave_creates_and_updates_draft_with_conflict_protection(self):
        response = self.client.post(
            reverse("draft_save"),
            {
                "owner_name": "測試車主",
                "id_front": self.image("front.png"),
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["revision"], 1)
        draft = OrderDraft.objects.get(pk=payload["id"])
        self.assertEqual(draft.data["owner_name"], "測試車主")
        self.assertTrue(draft.id_front)
        self.assertEqual(
            payload["updated_at"],
            timezone.localtime(draft.updated_at).strftime("%H:%M"),
        )

        updated = self.client.post(
            reverse("draft_save"),
            {
                "_draft_id": str(draft.pk),
                "_draft_revision": "1",
                "owner_name": "更新名稱",
            },
        )
        self.assertEqual(updated.json()["revision"], 2)

        conflict = self.client.post(
            reverse("draft_save"),
            {
                "_draft_id": str(draft.pk),
                "_draft_revision": "1",
                "owner_name": "舊頁面內容",
            },
        )
        self.assertEqual(conflict.status_code, 409)
        draft.refresh_from_db()
        self.assertEqual(draft.data["owner_name"], "更新名稱")

    def test_draft_can_resume_and_convert_to_formal_order(self):
        draft = OrderDraft.objects.create(
            data=self.complete_data(),
            id_front=self.image("front.png"),
            id_back=self.image("back.png"),
            created_by=self.user.username,
            updated_by=self.user.username,
        )

        resume = self.client.get(reverse("order_create"), {"draft": draft.pk})
        self.assertContains(resume, "繼續編輯草稿")
        self.assertContains(resume, "測試車主")
        self.assertContains(resume, "查看已暫存的正面照片")

        post_data = self.complete_data()
        post_data.update(
            {"_draft_id": str(draft.pk), "_draft_revision": str(draft.revision)}
        )
        response = self.client.post(reverse("order_create"), post_data)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(OrderDraft.objects.filter(pk=draft.pk).exists())
        order = SalesOrder.objects.get(owner_name="測試車主")
        self.assertEqual(order.status, SalesOrder.Status.CONTRACT_PENDING)
        self.assertTrue(order.id_front)
        self.assertTrue(order.id_back)

    def test_delete_draft_removes_saved_photos(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                draft = OrderDraft.objects.create(
                    data={"owner_name": "待刪除"},
                    id_front=self.image("front.png"),
                    created_by=self.user.username,
                )
                photo_path = Path(draft.id_front.path)
                self.assertTrue(photo_path.exists())

                response = self.client.post(reverse("draft_delete", args=[draft.pk]))

                self.assertRedirects(response, reverse("dashboard"))
                self.assertFalse(OrderDraft.objects.filter(pk=draft.pk).exists())
                self.assertFalse(photo_path.exists())
