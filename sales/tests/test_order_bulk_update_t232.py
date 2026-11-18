"""T-232 第 3a 版：訂單回匯批次修改（非金額欄位）。

匯出 → 在 Excel 改 → 匯回 → 三方比對預覽 → 確認後走訂單頁自動儲存同一段存檔流程整批寫入。
"""
import importlib
from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest import mock

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from sales.access.models import ScreenAccessGrant, UserAccessRevision, UserAccessState
from sales.models import OrderBulkUpdate, OrderChange, OrderEvent, OrderExportRecord, OrderOperationsProfile, SalesOrder
from sales.order_exchange import columns as cols
from sales.order_exchange import reimport
from sales.order_exchange.workbook import META_SHEET, SHEET_TITLE
from sales.tests import test_order_lifecycle as lifecycle
from sales.tests.test_order_workspace import form_data, formset_data

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
grant_migration = importlib.import_module("sales.migrations.0218_order_bulk_update_access")


class OrderBulkUpdateTests(lifecycle.OrderLifecycleTests.__bases__[0]):
    setUp_base = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def setUp(self):
        self.setUp_base()
        self.admin = get_user_model().objects.create_superuser("admin", password="Bulk-test-232!")
        self.client.force_login(self.admin)

    # ---- 輔助：照使用者的實際流程操作 ----
    def export_book(self, keys, **scope):
        response = self.client.post(reverse("order_export_download"), {"cols": keys, "tab": "all", **scope})
        self.assertEqual(response.status_code, 200, response.content[:200])
        return load_workbook(BytesIO(response.content))

    def set_cell(self, book, order, key, value):
        sheet = book[SHEET_TITLE]
        column = [cell.value for cell in sheet[1]].index(key)
        for row in sheet.iter_rows(min_row=3):
            if row[0].value == order.pk:
                row[column].value = value
                return
        self.fail(f"檔案裡沒有訂單 {order.pk}")

    def upload(self, book, name="改好的.xlsx"):
        buffer = BytesIO()
        book.save(buffer)
        response = self.client.post(reverse("order_bulk_update"),
                                    {"file": SimpleUploadedFile(name, buffer.getvalue(), content_type=XLSX)})
        return response

    def uploaded_batch(self, book, name="改好的.xlsx"):
        response = self.upload(book, name)
        self.assertEqual(response.status_code, 302)
        batch = OrderBulkUpdate.objects.latest("pk")
        self.assertEqual(response["Location"], reverse("order_bulk_update_detail", args=[batch.pk]))
        return batch

    def preview(self, batch):
        response = self.client.get(reverse("order_bulk_update_detail", args=[batch.pk]))
        self.assertEqual(response.status_code, 200)
        return response

    def apply(self, batch, **choices):
        fingerprint = self.preview(batch).context["plan"]["fingerprint"]
        data = {"fingerprint": fingerprint, **{key: "on" for key in choices}}
        return self.client.post(reverse("order_bulk_update_apply", args=[batch.pk]), data)

    def row_of(self, response, order):
        return next(item for item in response.context["plan"]["rows"] if item["id"] == str(order.pk))

    # ---- 主流程 ----
    def test_full_flow_writes_each_section_through_order_page_save(self):
        order, _vehicle = self.make_order()
        book = self.export_book(["owner_phone", "note", "trade_in_plate", "old_vehicle_brand", "battery_plan"])
        self.set_cell(book, order, "owner_phone", "0922333444")
        self.set_cell(book, order, "note", "批次改的備註")
        self.set_cell(book, order, "trade_in_plate", "OLD-0001")
        self.set_cell(book, order, "old_vehicle_brand", "山葉")
        self.set_cell(book, order, "battery_plan", "新方案")
        batch = self.uploaded_batch(book)

        page = self.preview(batch)
        self.assertEqual(page.context["plan"]["summary"]["changed"], 1)
        self.assertEqual(page.context["plan"]["summary"]["fields"], 5)
        self.assertContains(page, "0922333444")
        self.assertEqual(OrderChange.objects.filter(order=order).count(), 0)  # 預覽不寫

        response = self.apply(batch)
        self.assertRedirects(response, reverse("order_bulk_update_detail", args=[batch.pk]), fetch_redirect_response=False)
        order.refresh_from_db()
        profile = OrderOperationsProfile.objects.get(order=order)
        self.assertEqual((order.owner_phone, order.note, order.trade_in_plate), ("0922333444", "批次改的備註", "OLD-0001"))
        self.assertEqual((profile.old_vehicle_brand, profile.battery_plan), ("山葉", "新方案"))
        reason = "批次修改（改好的.xlsx 第 3 列）"
        # 訂車與配件、汰舊補助、舊車與報廢、車控與電池各走自己的存檔流程，各留一筆修改紀錄。
        self.assertEqual(OrderChange.objects.filter(order=order, reason=reason).count(), 4)
        self.assertTrue(OrderEvent.objects.filter(order=order, event_type="bulk_update", description__startswith=reason).exists())
        batch.refresh_from_db()
        self.assertEqual(batch.status, OrderBulkUpdate.Status.APPLIED)
        self.assertEqual((batch.result["orders"], batch.result["fields"]), (1, 5))
        self.assertContains(self.client.get(reverse("order_bulk_update_detail", args=[batch.pk])), "已寫入")

    def test_bulk_change_records_the_same_audit_as_autosave(self):
        from sales.forms import OrderEditForm, OrderPageAccessoryFormSet, OrderPageOtherFeeFormSet
        by_page, _ = self.make_order()
        by_file, _ = self.make_order()
        data = {**form_data(OrderEditForm(instance=by_page)),
                **formset_data(OrderPageAccessoryFormSet(instance=by_page, form_kwargs={"allow_manual": True})),
                **formset_data(OrderPageOtherFeeFormSet(instance=by_page, prefix="other_fees")),
                "_order_revision": str(by_page.revision), "_workspace": "1", "owner_phone": "0955000111", "note": "同一個修改"}
        self.assertEqual(self.client.post(reverse("order_edit", args=[by_page.pk]), data, HTTP_X_ORDER_WORKSPACE="1").status_code, 200)

        book = self.export_book(["owner_phone", "note"])
        self.set_cell(book, by_file, "owner_phone", "0955000111")
        self.set_cell(book, by_file, "note", "同一個修改")
        self.apply(self.uploaded_batch(book))

        page_change = OrderChange.objects.filter(order=by_page).latest("pk")
        file_change = OrderChange.objects.filter(order=by_file).latest("pk")
        self.assertEqual(page_change.reason, "修改訂單資料")
        self.assertTrue(file_change.reason.startswith("批次修改"))
        self.assertEqual(file_change.changes, page_change.changes)
        for name in ("owner_phone", "note", "actual_balance", "calculated_balance", "revision"):
            self.assertEqual(getattr(SalesOrder.objects.get(pk=by_file.pk), name),
                             getattr(SalesOrder.objects.get(pk=by_page.pk), name), name)

    # ---- 衝突、清除、忽略 ----
    def test_conflict_is_not_overwritten_unless_file_is_chosen(self):
        order, _vehicle = self.make_order()
        book = self.export_book(["owner_phone"])
        SalesOrder.objects.filter(pk=order.pk).update(owner_phone="0911999888")  # 匯出後有人在系統改了
        self.set_cell(book, order, "owner_phone", "0922333444")
        batch = self.uploaded_batch(book)
        field = self.row_of(self.preview(batch), order)["fields"][0]
        self.assertTrue(field["conflict"])
        self.assertEqual((field["base"], field["current"], field["new"]), ("0912345678", "0911999888", "0922333444"))

        self.apply(batch)  # 沒勾「以檔案為準」
        order.refresh_from_db()
        self.assertEqual(order.owner_phone, "0911999888")

        again = self.uploaded_batch(book)
        self.apply(again, **{f"take-3-owner_phone": True})
        order.refresh_from_db()
        self.assertEqual(order.owner_phone, "0922333444")

    def test_clearing_needs_confirmation_and_required_fields_cannot_be_cleared(self):
        order, _vehicle = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(note="要清掉的備註")
        book = self.export_book(["note", "owner_name"])
        self.set_cell(book, order, "note", None)
        self.set_cell(book, order, "owner_name", None)
        batch = self.uploaded_batch(book)
        item = self.row_of(self.preview(batch), order)
        self.assertIn("「車主名稱」不能清空；要改請填新的值。", item["errors"])
        response = self.apply(batch, **{"take-3-note": True})
        self.assertContains(self.client.get(response["Location"]), "沒有寫入任何資料")
        order.refresh_from_db()
        self.assertEqual(order.note, "要清掉的備註")

        book = self.export_book(["note"])
        self.set_cell(book, order, "note", None)
        clear_batch = self.uploaded_batch(book)
        self.apply(clear_batch)  # 沒勾確認清除
        order.refresh_from_db()
        self.assertEqual(order.note, "要清掉的備註")
        self.apply(self.uploaded_batch(book), **{"take-3-note": True})
        order.refresh_from_db()
        self.assertEqual(order.note, "")

    def test_id_number_and_readonly_changes_are_listed_but_ignored(self):
        order, _vehicle = self.make_order()
        book = self.export_book(["owner_id_number", "status", "total_income", "owner_phone"])
        self.set_cell(book, order, "owner_id_number", "B987654321")
        self.set_cell(book, order, "status", "已完成")
        self.set_cell(book, order, "total_income", 999999)
        batch = self.uploaded_batch(book)
        item = self.row_of(self.preview(batch), order)
        self.assertEqual(item["fields"], [])
        self.assertEqual({entry["reason"] for entry in item["ignored"]},
                         {reimport.IGNORED_ORDER_PAGE, reimport.IGNORED_READONLY})
        self.apply(batch)
        order.refresh_from_db()
        self.assertEqual(order.owner_id_number, "A123456789")

    # ---- 檔案層級的檢查 ----
    def test_new_duplicate_and_unknown_rows(self):
        first, _ = self.make_order()
        second, _ = self.make_order()
        book = self.export_book(["owner_phone"])
        sheet = book[SHEET_TITLE]
        sheet.append([None, "新增的列", "0900000000"])
        sheet.append([first.pk, first.number, "0933000000"])
        for row in sheet.iter_rows(min_row=3):
            if row[0].value == second.pk:
                row[0].value = 999999
        batch = self.uploaded_batch(book)
        page = self.preview(batch)
        self.assertEqual(page.context["plan"]["summary"]["skipped"], 1)
        errors = [message for item in page.context["plan"]["rows"] for message in item["errors"]]
        self.assertTrue(any("出現多次" in message for message in errors))
        self.assertTrue(any("找不到這張訂單" in message for message in errors))

    def test_foreign_tampered_or_expired_files_are_rejected(self):
        order, _vehicle = self.make_order()
        book = self.export_book(["owner_phone"])
        book[META_SHEET]["A2"] = "tampered"
        response = self.upload(book)
        self.assertEqual(response["Location"], reverse("order_bulk_update"))
        self.assertFalse(OrderBulkUpdate.objects.exists())

        book = self.export_book(["owner_phone"])
        OrderExportRecord.objects.update(created_at=timezone.now() - timedelta(days=cols.BASELINE_DAYS + 1))
        self.upload(book)
        self.assertFalse(OrderBulkUpdate.objects.exists())
        messages = [str(message) for message in self.client.get(reverse("order_bulk_update")).context["messages"]]
        self.assertTrue(any("超過 30 天" in message for message in messages))

    def test_row_limit_and_formula_cells(self):
        first, _ = self.make_order()
        self.make_order()
        book = self.export_book(["owner_phone"])
        with mock.patch.object(reimport, "MAX_ROWS", 1):
            self.upload(book)
        self.assertFalse(OrderBulkUpdate.objects.exists())
        self.set_cell(book, first, "owner_phone", "=A1")
        item = self.row_of(self.preview(self.uploaded_batch(book)), first)
        self.assertTrue(any("不能用公式" in message for message in item["errors"]))

    # ---- 整批交易 ----
    def test_changes_after_preview_stop_the_whole_batch(self):
        order, _vehicle = self.make_order()
        book = self.export_book(["owner_phone"])
        self.set_cell(book, order, "owner_phone", "0922333444")
        batch = self.uploaded_batch(book)
        fingerprint = self.preview(batch).context["plan"]["fingerprint"]
        SalesOrder.objects.filter(pk=order.pk).update(owner_phone="0911999888")
        self.client.post(reverse("order_bulk_update_apply", args=[batch.pk]), {"fingerprint": fingerprint})
        order.refresh_from_db()
        self.assertEqual(order.owner_phone, "0911999888")
        batch.refresh_from_db()
        self.assertEqual(batch.status, OrderBulkUpdate.Status.PREVIEW)
        self.assertIn("預覽之後訂單資料有變動", batch.last_error)

    def test_one_failing_row_rolls_back_every_row(self):
        good, _ = self.make_order()
        bad, _ = self.make_order()
        book = self.export_book(["owner_phone", "owner_email"])
        self.set_cell(book, good, "owner_phone", "0922333444")
        self.set_cell(book, bad, "owner_email", "not-an-email")
        batch = self.uploaded_batch(book)
        page = self.preview(batch)
        self.assertTrue(any("電子郵件" in message for message in self.row_of(page, bad)["validation"]))
        self.apply(batch)
        good.refresh_from_db()
        self.assertEqual(good.owner_phone, "0912345678")
        self.assertFalse(OrderChange.objects.exists())
        # 排除錯誤的那一列就能寫入其他列。
        row = self.row_of(page, bad)["row"]
        self.apply(batch, **{f"exclude-{row}": True})
        good.refresh_from_db()
        self.assertEqual(good.owner_phone, "0922333444")

    def test_delivered_order_needs_completed_correction(self):
        order, _vehicle = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(status=SalesOrder.Status.COMPLETED, delivered_at=timezone.now())
        book = self.export_book(["note"])
        self.set_cell(book, order, "note", "完成後補備註")
        batch = self.uploaded_batch(book)
        self.assertTrue(self.row_of(self.preview(batch), order)["needs_correction"])
        self.apply(batch)
        order.refresh_from_db()
        self.assertNotEqual(order.note, "完成後補備註")
        self.apply(batch, **{"correction-3": True})
        order.refresh_from_db()
        self.assertEqual(order.note, "完成後補備註")

    def test_cancelled_order_content_is_locked(self):
        order, _vehicle = self.make_order()
        book = self.export_book(["note"])
        SalesOrder.objects.filter(pk=order.pk).update(status=SalesOrder.Status.CANCELLED)
        self.set_cell(book, order, "note", "取消後改")
        item = self.row_of(self.preview(self.uploaded_batch(book)), order)
        self.assertIn("訂單已取消或在取消流程中，訂單內容已鎖定。", item["errors"])

    # ---- 權限 ----
    def staff(self, *grants):
        user = get_user_model().objects.create_user("bulk-staff", password="Bulk-test-232!")
        UserAccessState.objects.create(user=user, configured=True)
        for key, actions in grants:
            ScreenAccessGrant.objects.create(user=user, screen_key=key, view=True, **actions)
        self.client.force_login(user)
        return user

    def test_each_section_still_needs_its_order_page_permission(self):
        order, _vehicle = self.make_order()
        self.staff(("orders", {"operate": True, "export": True}), ("order_bulk_update", {"operate": True}))
        book = self.export_book(["note", "old_vehicle_brand"])
        self.set_cell(book, order, "note", "有權限")
        self.set_cell(book, order, "old_vehicle_brand", "沒權限")
        item = self.row_of(self.preview(self.uploaded_batch(book)), order)
        self.assertIn("你沒有「舊車與報廢」的操作權限，這一區的欄位不能修改。", item["errors"])

    def test_content_and_operations_need_order_finance_like_the_order_page(self):
        # 2.25.1：訂單頁的中介層對訂車與配件、營運資料的寫入另外要求「訂單內部財務」修改權限，回匯照做；
        # 汰舊補助資料的端點沒有這項要求，照樣可以改。
        order, _vehicle = self.make_order()
        self.staff(("orders", {"operate": True, "export": True}), ("work", {"operate": True}),
                   ("order_bulk_update", {"operate": True}))
        book = self.export_book(["note", "old_vehicle_brand", "trade_in_plate"])
        self.set_cell(book, order, "note", "沒有財務權限")
        self.set_cell(book, order, "old_vehicle_brand", "沒有財務權限")
        self.set_cell(book, order, "trade_in_plate", "OLD-9999")
        batch = self.uploaded_batch(book)
        item = self.row_of(self.preview(batch), order)
        self.assertIn("你沒有「訂車與配件」的操作權限，這一區的欄位不能修改。", item["errors"])
        self.assertIn("你沒有「舊車與報廢」的操作權限，這一區的欄位不能修改。", item["errors"])
        self.assertNotIn("你沒有「汰舊補助資料」的操作權限，這一區的欄位不能修改。", item["errors"])
        self.apply(batch)
        order.refresh_from_db()
        self.assertEqual(order.note, "")
        self.assertEqual(OrderOperationsProfile.objects.get(order=order).old_vehicle_brand, "")
        # 補上訂單內部財務修改權限後就能寫入（與訂單頁相同）。
        ScreenAccessGrant.objects.create(user=get_user_model().objects.get(username="bulk-staff"),
                                         screen_key="order_finance", view=True, operate=True)
        again = self.uploaded_batch(book)
        self.assertEqual(self.row_of(self.preview(again), order)["errors"], [])
        self.apply(again)
        order.refresh_from_db()
        self.assertEqual((order.note, order.trade_in_plate), ("沒有財務權限", "OLD-9999"))

    def test_bulk_update_screen_and_own_batches_only(self):
        order, _vehicle = self.make_order()
        book = self.export_book(["note"])
        batch = self.uploaded_batch(book)
        self.staff(("orders", {"operate": True, "export": True}))
        self.assertEqual(self.client.get(reverse("order_bulk_update")).status_code, 403)
        ScreenAccessGrant.objects.create(user=get_user_model().objects.get(username="bulk-staff"),
                                         screen_key="order_bulk_update", view=True, operate=True)
        self.assertEqual(self.client.get(reverse("order_bulk_update")).status_code, 200)
        self.assertEqual(self.client.get(reverse("order_bulk_update_detail", args=[batch.pk])).status_code, 404)

    # ---- migration 0218（Q3 A：上線時授權給所有現有帳號） ----
    def test_migration_grants_bulk_update_to_configured_accounts(self):
        configured = get_user_model().objects.create_user("configured", password="Bulk-test-232!")
        UserAccessState.objects.create(user=configured, configured=True, version=2)
        ScreenAccessGrant.objects.create(user=configured, screen_key="orders", view=True)
        legacy = get_user_model().objects.create_user("legacy", password="Bulk-test-232!")
        grant_migration.grant_bulk_update(apps, SimpleNamespace(connection=connection))
        grant = ScreenAccessGrant.objects.get(user=configured, screen_key="order_bulk_update")
        self.assertEqual((grant.view, grant.operate, grant.export), (True, True, False))
        revision = UserAccessRevision.objects.get(user=configured)
        self.assertEqual((revision.version, revision.actor_name), (3, grant_migration.ACTOR))
        self.assertFalse(ScreenAccessGrant.objects.filter(user=legacy).exists())
        grant_migration.grant_bulk_update(apps, SimpleNamespace(connection=connection))
        self.assertEqual(UserAccessRevision.objects.filter(user=configured).count(), 1)
