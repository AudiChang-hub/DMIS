"""「新舊車主不同人」反向勾選（使用者 2026-10-22 T-84）。

同一人居多，所以打勾＝不同人、不勾＝同一人（新單預設不勾）。資料庫照舊存 old_owner_same_as_owner，
既有訂單的意義、必備文件與補助完成條件都不變；只有畫面反向。
"""
import re

from django.test import TestCase
from django.urls import reverse

from sales.models import SalesOrder, SubsidyDocument
from sales.services.subsidy_programs import sync_trade_in_from_subsidies
from sales.tests import test_order_intake as intake_fixtures
from sales.tests import test_subsidy_tradein_t80 as t80


class IntakeOwnerDifferentTests(TestCase):
    setUp = intake_fixtures.OrderIntakeTests.setUp
    image = intake_fixtures.OrderIntakeTests.image
    complete_data = intake_fixtures.OrderIntakeTests.complete_data
    submit = intake_fixtures.OrderIntakeTests.submit

    def test_unchecked_means_same_owner(self):
        program = t80.trade_in_program()
        response = self.submit(subsidy_programs=[str(program.pk)], subsidy_programs_present="1")
        self.assertEqual(response.status_code, 302)
        order = SalesOrder.objects.get()
        self.assertTrue(order.old_owner_same_as_owner)
        self.assertNotIn(SubsidyDocument.DocumentType.OWNER_DECLARATION, order.required_subsidy_document_types())

    def test_checked_means_different_owner(self):
        program = t80.trade_in_program()
        response = self.submit(subsidy_programs=[str(program.pk)], subsidy_programs_present="1", old_owner_different="on")
        self.assertEqual(response.status_code, 302)
        order = SalesOrder.objects.get()
        self.assertFalse(order.old_owner_same_as_owner)
        self.assertEqual(order.old_owner_name, "")
        self.assertIn(SubsidyDocument.DocumentType.OWNER_DECLARATION, order.required_subsidy_document_types())
        self.assertIn("舊車主姓名", order.missing_subsidy_requirements())

    def test_create_form_asks_different_owner(self):
        t80.trade_in_program()
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_create")).content.decode()
        self.assertIn("新舊車主不同人", page)
        self.assertRegex(page, r'<input type="checkbox" name="old_owner_different"(?![^>]*checked)')
        self.assertNotIn('name="old_owner_same_as_owner"', page)
        self.assertNotIn("新舊車主為同一人", page)


class SubsidyPageHelpers(t80.lifecycle.OrderLifecycleTests.__bases__[0]):
    setUp = t80.SubsidyStepTests.setUp
    make_order = t80.SubsidyStepTests.make_order
    login_admin = t80.SubsidyStepTests.login_admin
    page = t80.SubsidyStepTests.page
    post_items = t80.SubsidyStepTests.post_items


class SubsidyOwnerDifferentTests(SubsidyPageHelpers):
    def trade_in_order(self, same):
        order, _vehicle = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(
            is_trade_in_subsidy=True, old_owner_same_as_owner=same, old_owner_name="" if same else "舊車主甲",
            old_owner_id_number="" if same else "B123456789")
        order.refresh_from_db()
        return order

    def post_owner(self, order, **extra):
        data = {"_order_revision": str(order.revision), "trade_in_plate": "ABC-1234", "old_owner_name": "舊車主乙",
                "old_owner_id_number": "c223456789", "old_owner_phone": "0912000000", **extra}
        return self.client.post(reverse("subsidy_data_update", args=[order.pk]), data)

    def test_existing_values_keep_meaning_on_screen(self):
        self.login_admin()
        same = self.trade_in_order(True)
        html = self.page(same)
        self.assertIn("<strong>新舊車主不同人</strong>", html)
        self.assertNotIn("新舊車主為同一人", html)
        self.assertRegex(html, r'<input type="checkbox" name="old_owner_different"(?![^>]*checked)')
        self.assertRegex(html, r'data-old-owner-same>')
        self.assertEqual(len(re.findall(r"data-old-owner-field hidden", html)), 3)
        different = self.trade_in_order(False)
        html = self.page(different)
        self.assertRegex(html, r'<input type="checkbox" name="old_owner_different"[^>]*checked')
        self.assertIn("data-old-owner-same hidden", html)
        self.assertNotIn("data-old-owner-field hidden", html)

    def test_requirements_follow_stored_value_unchanged(self):
        same, different = self.trade_in_order(True), self.trade_in_order(False)
        # 補助文件改選填（T-95）：已備妥件數只算資料（不同人多舊車主姓名、證號），聲明書改列在應備文件。
        self.assertEqual(different.subsidy_required_count - same.subsidy_required_count, 2)
        self.assertEqual(different.subsidy_document_progress()[1] - same.subsidy_document_progress()[1], 1)
        self.assertIn(SubsidyDocument.DocumentType.OWNER_DECLARATION, different.required_subsidy_document_types())
        self.assertNotIn(SubsidyDocument.DocumentType.OWNER_DECLARATION, same.required_subsidy_document_types())

    def test_save_unchecked_is_same_owner(self):
        self.login_admin()
        order = self.trade_in_order(False)
        self.post_owner(order)
        order.refresh_from_db()
        self.assertTrue(order.old_owner_same_as_owner)
        self.assertEqual(order.old_owner_name, order.owner_name)

    def test_save_checked_is_different_owner(self):
        self.login_admin()
        order = self.trade_in_order(True)
        self.post_owner(order, old_owner_different="on")
        order.refresh_from_db()
        self.assertFalse(order.old_owner_same_as_owner)
        self.assertEqual((order.old_owner_name, order.old_owner_id_number), ("舊車主乙", "C223456789"))

    def test_without_trade_in_save_does_not_touch_stored_value(self):
        self.login_admin()
        order, _vehicle = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(is_trade_in_subsidy=False, old_owner_same_as_owner=False)
        order.refresh_from_db()
        self.assertNotIn('name="old_owner_different"', self.page(order))
        self.post_owner(order)
        order.refresh_from_db()
        self.assertFalse(order.old_owner_same_as_owner)
        self.assertEqual(order.old_owner_name, "舊車主乙")

    def test_removing_trade_in_returns_to_default_same_owner(self):
        order = self.trade_in_order(False)
        sync_trade_in_from_subsidies(order)
        order.refresh_from_db()
        self.assertEqual((order.is_trade_in_subsidy, order.old_owner_same_as_owner), (False, True))
