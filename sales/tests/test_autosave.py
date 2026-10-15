"""1.81.0：訂單頁各區塊自動儲存，不再有「儲存」按鈕；完成領牌仍需明確按下。"""
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from sales.models import RegistrationDocument, SalesOrder
from sales.tests import test_order_flow as flow

order_step_url = flow.order_step_url


class OrderAutosaveTests(TestCase):
    setUp = flow.OrderFlowTests.setUp
    make_order = flow.OrderFlowTests.make_order

    def workspace_post(self, url, data):
        return self.client.post(url, data, HTTP_X_ORDER_WORKSPACE="1", HTTP_ACCEPT="application/json")

    def test_registration_autosave_saves_data_without_finishing(self):
        order = self.make_order()
        order.allocate(self.vehicle)
        for document_type in RegistrationDocument.active_fixed_document_types():
            RegistrationDocument.objects.create(order=order, document_type=document_type,
                                                file=SimpleUploadedFile(f"{document_type}.pdf", b"doc", content_type="application/pdf"))
        self.client.force_login(self.user)
        page = self.client.get(order_step_url(order.pk, "registration")).content.decode()
        self.assertIn('data-workspace-save="registration"', page)
        self.assertNotIn("儲存領牌資料", page)
        self.assertNotIn("儲存並完成領牌", page)

        response = self.workspace_post(reverse("registration_save", args=[order.pk]),
                                       {"registration_date": "2026-07-29", "final_plate_number": "abc-1234"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("financial_revision", payload)
        self.assertIn("確認領牌完成", payload["registration_html"])
        order.refresh_from_db()
        self.assertEqual(order.final_plate_number, "ABC-1234")
        # 文件齊全也不自動完成：完成會鎖定日期與車牌，要由人員按「確認領牌完成」。
        self.assertFalse(order.is_registration_complete)

        response = self.workspace_post(reverse("registration_save", args=[order.pk]),
                                       {"registration_date": "", "final_plate_number": "abc-1234"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("registration_date", response.json()["errors"])

    def test_completed_registration_fields_are_locked(self):
        order = self.make_order()
        order.allocate(self.vehicle)
        SalesOrder.objects.filter(pk=order.pk).update(registration_date="2026-07-29", final_plate_number="ABC-1234")
        for document_type in RegistrationDocument.active_fixed_document_types():
            RegistrationDocument.objects.create(order=order, document_type=document_type,
                                                file=SimpleUploadedFile(f"{document_type}.pdf", b"doc", content_type="application/pdf"))
        order.refresh_from_db()
        order.complete_registration("tester")
        self.client.force_login(self.user)
        response = self.client.get(order_step_url(order.pk, "registration"))
        self.assertTrue(response.context["registration_form"]["final_plate_number"].field.disabled)
        response = self.workspace_post(reverse("registration_save", args=[order.pk]),
                                       {"registration_date": "2026-08-01", "final_plate_number": "XYZ-0000"})
        self.assertEqual(response.status_code, 409)

    def test_workspace_sections_have_no_save_buttons(self):
        order = self.make_order()
        order.allocate(self.vehicle)
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        for label in ("儲存補助撥款與舊車資料", "儲存交車前確認", "儲存收支與後續資料", "補助資料已儲存", "data-subsidy-save-dock"):
            self.assertNotIn(label, page)
        self.assertIn("data-autosave-status", page)
        # 確認入帳會鎖定金額，勾選前先確認。
        self.assertIn("data-autosave-confirm", page)
        script = Path("static/js/order-workspace.js").read_text(encoding="utf-8")
        self.assertIn("AUTOSAVE_DELAY", script)
        self.assertIn("typed.has(name) ? 'keep'", script)


class DataMaintenanceDraftTests(TestCase):
    """1.83.0：資料維護區輸入自動保留成草稿，按「套用」才生效。"""

    def test_data_maintenance_pages_keep_drafts_and_apply_button(self):
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_superuser("draft-root", password="test-only")
        self.client.force_login(user)
        page = self.client.get(reverse("sales_source_category_list")).content.decode()
        self.assertIn("js/form-draft.js", page)
        self.assertIn("新增類別", page)
        script = Path("static/js/form-draft.js").read_text(encoding="utf-8")
        for skipped in ("'password'", "'file'", "'hidden'"):
            self.assertIn(skipped, script)
        self.assertIn("storage.removeItem(key)", script)
        for name in ("vehicle_model_price_versions", "settlement_cost_rule_form", "incentive_rule_form"):
            template = Path(f"templates/sales/{name}.html").read_text(encoding="utf-8")
            self.assertIn("套用", template)
        # 訂單頁不載入草稿腳本（訂單頁是直接自動儲存）。
        self.assertNotIn("js/form-draft.js", Path("templates/sales/order_detail.html").read_text(encoding="utf-8"))
