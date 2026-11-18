"""T-232 第 1 版：訂單匯出（自選欄位、預覽後才匯出 xlsx、留匯出紀錄）。"""
from io import BytesIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.urls import reverse
from openpyxl import load_workbook

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import OrderEvent, OrderExportRecord, SalesOrder
from sales.order_exchange import columns as cols
from sales.order_exchange.workbook import META_SHEET, SHEET_TITLE, unsign_token
from sales.tests import test_order_lifecycle as lifecycle


class OrderExportTests(lifecycle.OrderLifecycleTests.__bases__[0]):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def login_admin(self):
        admin = get_user_model().objects.create_superuser("admin", password="Export-test-232!")
        self.client.force_login(admin)
        return admin

    def login_staff(self, *grants):
        user = get_user_model().objects.create_user("staff232", password="Export-test-232!")
        UserAccessState.objects.create(user=user, configured=True)
        for key, actions in grants:
            ScreenAccessGrant.objects.create(user=user, screen_key=key, view=True, **actions)
        self.client.force_login(user)
        return user

    def download(self, keys, **scope):
        return self.client.post(reverse("order_export_download"), {"cols": keys, **scope})

    def open_book(self, response):
        return load_workbook(BytesIO(response.content))

    def test_passwords_are_never_exportable(self):
        keys = set(cols.COLUMN_BY_KEY)
        self.assertFalse({"vehicle_control_password", "battery_password"} & keys)
        self.assertFalse(any("password" in key for key in keys))

    def test_editable_columns_are_only_the_first_batch(self):
        editable = {column.key for column in cols.COLUMNS if column.editable}
        # 金額、狀態、領牌、車型車色、子表、收支與淨利一律只能看。
        for key in ("vehicle_price", "plate_insurance_fee", "payment_type", "status", "registration_date",
                    "final_plate_number", "vehicle_model", "color", "accessories", "actual_balance",
                    "net_profit", "total_income", "dealer_commission_expense", "bank_name", "remittance_account",
                    "deposit_amount", "source", "commission_recipient"):
            self.assertNotIn(key, editable, key)
        for key in ("owner_name", "owner_phone", "owner_id_number", "delivery_destination", "trade_in_plate",
                    "old_vehicle_engine_number", "battery_account"):
            self.assertIn(key, editable, key)

    def test_page_lists_groups_and_preview_is_read_only(self):
        self.login_admin()
        order, _vehicle = self.make_order()
        page = self.client.get(reverse("order_export"))
        self.assertEqual(page.status_code, 200)
        html = page.content.decode()
        self.assertIn("選擇欄位", html)
        self.assertIn('value="owner_phone"', html)
        self.assertNotIn('id="preview"', html)

        response = self.client.get(reverse("order_export"), {"cols": ["owner_name", "owner_phone", "vehicle_price"], "preview": "1"})
        html = response.content.decode()
        self.assertIn('id="preview"', html)
        self.assertIn(order.number, html)
        self.assertIn("王小明", html)
        self.assertIn("75,000", html)
        self.assertIn("確認匯出 Excel（1 張）", html)
        self.assertFalse(OrderExportRecord.objects.exists())

    def test_download_builds_reimportable_workbook_and_records_export(self):
        admin = self.login_admin()
        order, _vehicle = self.make_order()
        response = self.download(["owner_name", "owner_phone", "vehicle_price", "registration_date"])
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment;", response["Content-Disposition"])
        record = OrderExportRecord.objects.get()
        self.assertEqual(record.created_by, admin)
        self.assertEqual(record.row_count, 1)
        self.assertEqual(record.columns, ["number", "registration_date", "owner_name", "owner_phone", "vehicle_price"])
        self.assertFalse(record.contains_pii)
        # 基準值只存之後可回匯的欄位，另記當時的訂單版本。
        self.assertEqual(record.baseline[str(order.pk)], {"revision": order.revision,
                                                           "values": {"owner_name": "王小明", "owner_phone": "0912345678"}})

        book = self.open_book(response)
        sheet = book[SHEET_TITLE]
        self.assertTrue(sheet.row_dimensions[1].hidden)
        self.assertEqual([cell.value for cell in sheet[1]], ["id", *record.columns])
        self.assertEqual([cell.value for cell in sheet[2]],
                         ["系統編號（請勿修改）", "訂單編號（唯讀）", "領牌日（唯讀）", "車主姓名／公司名稱", "電話", "成交車價（唯讀）"])
        self.assertEqual([cell.value for cell in sheet[3]], [order.pk, order.number, None, "王小明", "0912345678", 75000])
        self.assertEqual(book[META_SHEET].sheet_state, "veryHidden")
        self.assertEqual(unsign_token(book[META_SHEET]["A2"].value), str(record.token))

    def test_required_order_number_and_unknown_columns(self):
        self.login_admin()
        self.make_order()
        self.download(["owner_phone", "no_such_column", "vehicle_control_password"])
        self.assertEqual(OrderExportRecord.objects.get().columns, ["number", "owner_phone"])

    def test_formula_text_is_neutralised(self):
        self.login_admin()
        order, _vehicle = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(note="=HYPERLINK(\"http://x\")")
        sheet = self.open_book(self.download(["note"]))[SHEET_TITLE]
        self.assertEqual(sheet["C3"].value, "'=HYPERLINK(\"http://x\")")

    def test_scope_follows_order_list_search(self):
        self.login_admin()
        first, _ = self.make_order()
        second, _ = self.make_order()
        SalesOrder.objects.filter(pk=second.pk).update(owner_name="陳大華")
        from sales.services.order_search import rebuild_order_search_index
        rebuild_order_search_index(second.pk)
        self.download(["owner_name"], q="陳大華")
        record = OrderExportRecord.objects.get()
        self.assertEqual(list(record.baseline), [str(second.pk)])
        self.assertEqual(record.scope["params"], {"q": "陳大華"})
        self.assertNotIn(str(first.pk), record.baseline)

    def test_over_limit_is_rejected_without_record(self):
        self.login_admin()
        self.make_order()
        self.make_order()
        with mock.patch.object(cols, "EXPORT_LIMIT", 1):
            response = self.download(["owner_name"])
            self.assertEqual(response.status_code, 302)
            html = self.client.get(reverse("order_export"), {"cols": ["owner_name"], "preview": "1"}).content.decode()
        self.assertFalse(OrderExportRecord.objects.exists())
        self.assertIn("超過每次 1 張的上限", html)

    def test_download_needs_preview_selection(self):
        self.login_admin()
        self.make_order()
        response = self.client.post(reverse("order_export_download"), {})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(OrderExportRecord.objects.exists())

    def test_payout_account_export_is_logged_per_order(self):
        self.login_admin()
        order, _vehicle = self.make_order()
        self.download(["owner_name", "remittance_account"])
        record = OrderExportRecord.objects.get()
        self.assertTrue(record.contains_pii)
        self.assertTrue(OrderEvent.objects.filter(order=order, event_type="payout_account_viewed").exists())

    def test_without_export_grant_routes_are_forbidden(self):
        self.login_staff(("orders", {"operate": True}))
        self.make_order()
        self.assertEqual(self.client.get(reverse("order_export")).status_code, 403)
        self.assertEqual(self.download(["owner_name"]).status_code, 403)
        self.assertNotIn(reverse("order_export"), self.client.get(reverse("order_list")).content.decode())

    def test_finance_and_profit_columns_need_their_grants(self):
        self.login_staff(("orders", {"export": True}))
        self.make_order()
        html = self.client.get(reverse("order_export")).content.decode()
        self.assertIn("需要「查看淨利」的匯出授權", html)
        self.download(["owner_name", "net_profit", "total_income", "remittance_account"])
        record = OrderExportRecord.objects.get()
        self.assertEqual(record.columns, ["number", "owner_name"])
        self.assertFalse(record.contains_profit or record.contains_finance)

    def test_profit_column_for_granted_user(self):
        self.login_admin()
        order, _vehicle = self.make_order()
        sheet = self.open_book(self.download(["net_profit", "total_income"]))[SHEET_TITLE]
        self.assertEqual(sheet["C2"].value, "總收入（唯讀）")
        self.assertEqual(sheet["D2"].value, "單筆淨利（唯讀）")
        record = OrderExportRecord.objects.get()
        self.assertTrue(record.contains_profit and record.contains_finance)

    def test_order_list_links_to_export_with_current_filters(self):
        self.login_admin()
        html = self.client.get(reverse("order_list"), {"q": "王"}).content.decode()
        self.assertIn(f'{reverse("order_export")}?q=%E7%8E%8B', html)
