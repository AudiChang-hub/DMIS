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

    def test_registration_autosave_saves_data_and_finishes(self):
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
        self.assertIn("領牌已完成", payload["registration_html"])
        order.refresh_from_db()
        self.assertEqual(order.final_plate_number, "ABC-1234")
        # 日期與車牌填好就自動完成（使用者 2026-11-11 T-147，取代 10-15「由人員按確認領牌完成」）。
        self.assertTrue(order.is_registration_complete)

        response = self.workspace_post(reverse("registration_save", args=[order.pk]),
                                       {"registration_date": "", "final_plate_number": "abc-1234"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("registration_date", response.json()["errors"])

    def test_completed_registration_fields_stay_editable(self):
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
        # 領牌完成後仍可修改（使用者 2026-11-11 T-147，取代完成即鎖定）。
        self.assertFalse(response.context["registration_form"]["final_plate_number"].field.disabled)
        response = self.workspace_post(reverse("registration_save", args=[order.pk]),
                                       {"registration_date": "2026-08-01", "final_plate_number": "XYZ-0000"})
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual((str(order.registration_date), order.final_plate_number), ("2026-08-01", "XYZ-0000"))

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

    def test_autosave_resends_after_reconnect_without_raw_browser_errors(self):
        """UAT U-08：恢復連線先三方合併最新頁面再補送；失敗訊息不直接顯示瀏覽器英文原文。"""
        script = Path("static/js/order-workspace.js").read_text(encoding="utf-8")
        self.assertIn("window.addEventListener('online', resume)", script)
        self.assertIn("syncFrom(new DOMParser()", script)
        self.assertIn("offlineText(unsavedLabels(form))", script)
        self.assertNotIn(": error.message;", script)


class DataMaintenanceDraftTests(TestCase):
    """1.83.0：資料維護區輸入自動保留成草稿，按「套用」才生效。"""

    def test_data_maintenance_pages_keep_drafts_and_apply_button(self):
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_superuser("draft-root", password="test-only")
        self.client.force_login(user)
        page = self.client.get(reverse("installment_company_list")).content.decode()
        self.assertIn("js/form-draft.js", page)
        self.assertIn("新增分期公司", page)
        script = Path("static/js/form-draft.js").read_text(encoding="utf-8")
        for skipped in ("'password'", "'file'", "'hidden'"):
            self.assertIn(skipped, script)
        self.assertIn("storage.removeItem(key)", script)
        for name in ("vehicle_model_price_versions", "settlement_cost_rule_form", "incentive_campaign_form",
                     "dealer_reward_campaign_form"):
            template = Path(f"templates/sales/{name}.html").read_text(encoding="utf-8")
            self.assertIn("套用", template)
        # UAT U-11：頁尾「放棄變更／取消」也會清掉本機草稿，提示框按鈕同名同效果。
        self.assertIn("a[data-discard-draft]", script)
        self.assertIn("/^(放棄|取消)/", script)
        self.assertNotIn("捨棄草稿", script)
        for name in ("catalog_edit", "vehicle_model_form"):
            template = Path(f"templates/sales/{name}.html").read_text(encoding="utf-8")
            self.assertIn('class="button ghost" data-discard-draft', template)
        # 訂單頁不載入草稿腳本（訂單頁是直接自動儲存）。
        self.assertNotIn("js/form-draft.js", Path("templates/sales/order_detail.html").read_text(encoding="utf-8"))
