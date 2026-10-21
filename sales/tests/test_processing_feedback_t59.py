"""T-59（使用者 2026-10-21）：「仍在處理」過久——下載不再卡提示、OCR 不佔訂單鎖、訂單頁少查詢。"""
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from sales.models import SalesOrder, SubsidyDocument, VehicleColor, VehicleModel
from sales.tests import test_order_flow as flow


class DownloadCookieTests(TestCase):
    setUp = flow.OrderFlowTests.setUp

    def test_attachment_response_sets_short_cookie_for_busy_indicator(self):
        admin = self.user.__class__.objects.create_superuser("admin", password="test-only")
        self.client.force_login(admin)
        exported = self.client.get(reverse("operations_report_export"))
        self.assertTrue(exported["Content-Disposition"].startswith("attachment"))
        cookie = exported.cookies["dmis_download"]
        self.assertEqual(cookie["max-age"], 60)
        self.assertFalse(cookie["httponly"])
        page = self.client.get(reverse("order_list"))
        self.assertNotIn("dmis_download", page.cookies)


class OldOwnerOcrLockTests(TestCase):
    setUp = flow.OrderFlowTests.setUp
    make_order = flow.OrderFlowTests.make_order

    def test_ocr_runs_after_order_lock_is_released(self):
        order = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(is_trade_in_subsidy=True, old_owner_same_as_owner=False)
        self.client.force_login(self.user)
        baseline = len(connection.atomic_blocks)
        depth = []

        def recognize(front, back):
            # 測試本身包在交易內；辨識時不應再多一層（訂單 select_for_update 的那層已結束）。
            depth.append(len(connection.atomic_blocks))
            return {"fields": {"name": "陳大華", "id_number": "B123456789"}, "warnings": []}

        with patch("sales.views.recognize_id_card", side_effect=recognize):
            for document_type, name in ((SubsidyDocument.DocumentType.OLD_OWNER_ID_FRONT, "front.jpg"),
                                        (SubsidyDocument.DocumentType.OLD_OWNER_ID_BACK, "back.jpg")):
                self.client.post(reverse("subsidy_document_upload", args=[order.pk]),
                                 {"document_type": document_type, "file": flow.uploaded_test_jpeg(name)})
        self.assertEqual(depth, [baseline])
        order.refresh_from_db()
        self.assertEqual((order.old_owner_name, order.old_owner_id_number), ("陳大華", "B123456789"))
        self.assertTrue(order.changes.filter(reason="舊車主證件 OCR 自動辨識").exists())


class OrderPageQueryTests(TestCase):
    setUp = flow.OrderFlowTests.setUp
    make_order = flow.OrderFlowTests.make_order

    def page_queries(self, order):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("order_detail", args=[order.pk]))
        self.assertEqual(response.status_code, 200)
        return len(queries)

    def test_more_colors_do_not_add_queries(self):
        admin = self.user.__class__.objects.create_superuser("admin", password="test-only")
        order = self.make_order()
        self.client.force_login(admin)
        self.page_queries(order)
        before = self.page_queries(order)
        for index in range(6):
            model = VehicleModel.objects.create(brand="測試廠牌", name=f"車型 {index}")
            VehicleColor.objects.create(vehicle_model=model, name="黑")
            VehicleColor.objects.create(vehicle_model=model, name="白")
        self.assertEqual(self.page_queries(order), before)

    def test_vehicle_rate_data_is_one_query(self):
        from sales.views import _vehicle_rate_data
        for index in range(4):
            VehicleModel.objects.create(brand="測試廠牌", name=f"費率 {index}")
        with self.assertNumQueries(1):
            data = _vehicle_rate_data()
        self.assertIn("electric_registration_class", data[str(self.model.pk)])
