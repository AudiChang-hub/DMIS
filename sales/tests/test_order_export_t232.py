"""T-232 第 1 版：訂單匯出（自選欄位、預覽後才匯出 xlsx、留匯出紀錄）。

使用者 2026-11-18 定案：預設欄位＝舊「匯出營運資料」那組（Q9），舊按鈕拿掉、舊網址導到新流程；
人工可改的欄位都標成可回匯（Q4），車主證件號碼只能在訂單頁改（Q5），基準值保存 30 天（Q7）。
"""
from datetime import timedelta
from io import BytesIO
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import OrderEvent, OrderExportRecord, OrderOperationsProfile, SalesOrder
from sales.order_exchange import columns as cols
from sales.order_exchange.retention import expire_baselines, is_expired
from sales.order_exchange.workbook import META_SHEET, READONLY_NOTE, SHEET_TITLE, unsign_token
from sales.tests import test_order_lifecycle as lifecycle

# 舊「匯出營運資料（目前篩選）」的表頭（2.22.3 版 views.operations_report_export），其後接 11 欄匯入的原始財務欄位。
LEGACY_HEADERS = (
    '訂單編號', '訂單日期', '車種', '型號', '型式', '顏色', '引擎／車身號碼', '車主名稱', '車牌號碼', '車款售價', '實際撥款', '成本', '總收款金額',
    '確認收款', '分期公司', '期數', '每期金額', '分期公司確認匯款', '身分證字號', '西元生日', '民國生日', '戶籍地址', '手機', 'Email', '自送托運地點',
    '發票日期', '尾款發票號碼', '補助方案', '補助金額', '銀行', '匯款帳戶', '申請日', '工業局補助進度', '環境部補助進度', '地方政府補助進度', '舊車車主',
    '舊車車主身分證', '舊車牌照號碼', '舊車引擎號碼', '舊車廠牌', '排氣量', '出廠日期', '報廢日期', '回收日期', '領牌稅金支出', '強制險支出', '選號支出',
    '贈品支出', '運費支出', '車行傭金支出', '銀行刷卡手續費支出', '領牌稅金收入', '強制險收入', '代辦費收入', '選號收入', '分期手續費收入', '刷卡手續費收入',
    '其他收入', '報廢代辦收入', '報廢車收入', '實銷獎勵金', '促銷補助金', '分期補貼息', '強制險傭金', '信用卡傭金', '車控帳號', '電池合約方案', '電池合約啟用日期',
    '電池合約帳號', '安全帽', '公司禮券、匯款', '其他', '平台贈品', '客服電話', '分期資訊', '車行', '總收入', '總支出', '單筆淨利', '台數與傭金歸屬車行',
    '訂單成立日期',
)
LEGACY_IMPORTED = (
    "legacy_card_fee_expense", "installment_fee_expense", "used_vehicle_expense", "gift_shipping_expense",
    "friendly_dealer_bonus_expense", "first_sale_bonus_expense", "volume_bonus_expense",
    "used_vehicle_income", "card_installment_fee_income", "yamaha_bonus_income", "friendly_dealer_bonus_income",
)


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

    # ---- 欄位宣告 ----
    def test_default_columns_are_the_legacy_operations_export(self):
        legacy_labels = (*LEGACY_HEADERS, *[str(OrderOperationsProfile._meta.get_field(name).verbose_name)
                                            for name in LEGACY_IMPORTED])
        self.assertEqual(len(legacy_labels), 92)
        self.assertEqual(tuple(cols.COLUMN_BY_KEY[key].label for key in cols.DEFAULT_COLUMNS), legacy_labels)

    def test_passwords_are_never_exportable(self):
        self.assertFalse(any("password" in key for key in cols.COLUMN_BY_KEY))

    def test_editable_columns_follow_user_decisions(self):
        editable = {column.key for column in cols.COLUMNS if column.editable}
        # Q2＋Q4：人工可以改的欄位都可回匯，含金額、付款與分期、來源與歸屬、收支頁人工金額。
        for key in ("owner_name", "owner_phone", "owner_birth_date", "delivery_destination", "note", "trade_in_plate",
                    "old_owner_name", "old_vehicle_engine_number", "battery_account", "vehicle_price",
                    "plate_insurance_fee", "payment_type", "installment_periods", "source", "assigned_commission_recipient",
                    "gift_expense", "vehicle_cost", "actual_disbursement", "dealer_commission_expense", "used_vehicle_income"):
            self.assertIn(key, editable, key)
        # 系統算出、同步帶入、停用欄位與狀態只能看。
        for key in ("number", "status", "registration_date", "final_plate_number", "vehicle_model", "color",
                    "actual_balance", "discounted_total", "deposit_amount", "approved_discount_amount", "accessories",
                    "total_income", "total_expense", "net_profit", "total_received", "card_fee_income", "card_fee_expense",
                    "installment_fee_income", "dealer_name", "payment_confirmed", "commission_recipient", "subsidy_amount",
                    "helmet", "invoice_date", "bank_name", "remittance_account", "owner_birth_roc"):
            self.assertNotIn(key, editable, key)
        # Q5：車主證件號碼可以匯出，但只能在訂單頁改。
        owner_id = cols.COLUMN_BY_KEY["owner_id_number"]
        self.assertFalse(owner_id.editable)
        self.assertTrue(owner_id.order_page_only)

    # ---- 頁面與預覽 ----
    def test_page_defaults_to_legacy_columns_and_preview_is_read_only(self):
        self.login_admin()
        order, _vehicle = self.make_order()
        html = self.client.get(reverse("order_export")).content.decode()
        self.assertIn("選擇欄位", html)
        self.assertIn('value="net_profit" checked', html)
        self.assertNotIn('value="status" checked', html)
        self.assertIn("只能在訂單頁改", html)
        self.assertNotIn('id="preview"', html)

        response = self.client.get(reverse("order_export"), {"cols": ["owner_name", "owner_phone", "vehicle_price"], "preview": "1"})
        html = response.content.decode()
        self.assertIn('id="preview"', html)
        self.assertIn(order.number, html)
        self.assertIn("王小明", html)
        self.assertIn("75,000", html)
        self.assertIn("確認匯出 Excel（1 張）", html)
        self.assertFalse(OrderExportRecord.objects.exists())

    # ---- 下載與紀錄 ----
    def test_download_builds_reimportable_workbook_and_records_export(self):
        admin = self.login_admin()
        order, _vehicle = self.make_order()
        response = self.download(["owner_name", "owner_phone", "vehicle_price", "registration_date"])
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment;", response["Content-Disposition"])
        record = OrderExportRecord.objects.get()
        self.assertEqual(record.created_by, admin)
        self.assertEqual(record.row_count, 1)
        self.assertEqual(record.columns, ["number", "owner_name", "vehicle_price", "owner_phone", "registration_date"])
        self.assertFalse(record.contains_pii)
        # 基準值只存可回匯的欄位，另記當時的訂單版本。
        self.assertEqual(record.baseline[str(order.pk)], {
            "revision": order.revision,
            "values": {"owner_name": "王小明", "vehicle_price": "75000", "owner_phone": "0912345678"}})

        book = self.open_book(response)
        sheet = book[SHEET_TITLE]
        self.assertTrue(sheet.row_dimensions[1].hidden)
        self.assertEqual([cell.value for cell in sheet[1]], ["id", *record.columns])
        self.assertEqual([cell.value for cell in sheet[2]], ["系統編號（請勿修改）", "訂單編號", "車主名稱", "車款售價", "手機", "領牌日"])
        self.assertEqual(sheet["B2"].comment.text, READONLY_NOTE)
        self.assertIsNone(sheet["C2"].comment)
        self.assertEqual([cell.value for cell in sheet[3]], [order.pk, order.number, "王小明", 75000, "0912345678", None])
        self.assertEqual(book[META_SHEET].sheet_state, "veryHidden")
        self.assertEqual(unsign_token(book[META_SHEET]["A2"].value), str(record.token))

    def test_owner_id_number_header_says_order_page_only(self):
        self.login_admin()
        order, _vehicle = self.make_order()
        sheet = self.open_book(self.download(["owner_id_number"]))[SHEET_TITLE]
        self.assertEqual(sheet["C2"].value, "身分證字號")
        self.assertIn("訂單頁", sheet["C2"].comment.text)
        # 只能在訂單頁改的欄位不存基準值，回匯時一律忽略。
        self.assertEqual(OrderExportRecord.objects.get().baseline[str(order.pk)]["values"], {})

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

    # ---- 基準值保存 30 天（Q7） ----
    def test_baselines_expire_after_thirty_days_and_keep_summary(self):
        self.login_admin()
        self.make_order()
        self.download(["owner_name"])
        old = OrderExportRecord.objects.get()
        OrderExportRecord.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=cols.BASELINE_DAYS, minutes=1))
        self.assertEqual(self.download(["owner_phone"]).status_code, 200)  # 每次確認匯出順手清到期的基準值
        old.refresh_from_db()
        self.assertEqual(old.baseline, {})
        self.assertIsNotNone(old.baseline_cleared_at)
        self.assertTrue(is_expired(old))
        self.assertEqual((old.row_count, old.columns), (1, ["number", "owner_name"]))
        fresh = OrderExportRecord.objects.exclude(pk=old.pk).get()
        self.assertTrue(fresh.baseline)
        self.assertFalse(is_expired(fresh))
        self.assertEqual(expire_baselines(), 0)

    # ---- 權限 ----
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
        self.make_order()
        sheet = self.open_book(self.download(["net_profit", "total_income"]))[SHEET_TITLE]
        self.assertEqual(sheet["C2"].value, "總收入")
        self.assertEqual(sheet["D2"].value, "單筆淨利")
        record = OrderExportRecord.objects.get()
        self.assertTrue(record.contains_profit and record.contains_finance)

    # ---- 全部訂單頁只留一顆「匯出」、舊網址導到新流程（Q9） ----
    def test_order_list_has_single_export_button_with_current_filters(self):
        self.login_admin()
        html = self.client.get(reverse("order_list"), {"q": "王"}).content.decode()
        self.assertIn(f'<a class="button ghost" href="{reverse("order_export")}?q=%E7%8E%8B" data-order-export-link>匯出</a>', html)
        self.assertNotIn("匯出營運資料", html)
        self.assertNotIn(reverse("operations_report_export"), html)

    def test_legacy_operations_export_url_redirects_with_old_scope(self):
        self.login_admin()
        response = self.client.get(reverse("operations_report_export"),
                                   {"date_from": "2026-08-01", "date_to": "2026-08-31", "page": "3"})
        target = urlsplit(response["Location"])
        self.assertEqual(target.path, reverse("order_export"))
        self.assertEqual(parse_qs(target.query), {"date_from": ["2026-08-01"], "date_to": ["2026-08-31"],
                                                  "tab": ["all"], "business_only": ["1"]})
        response = self.client.get(reverse("operations_report_export"), {"include_cancelled": "1", "business_only": "1"})
        self.assertEqual(parse_qs(urlsplit(response["Location"]).query), {"include_cancelled": ["1"], "tab": ["all"]})
        self.assertEqual(self.client.get(reverse("operations_report_export"), {"date_from": "not-a-date"}).status_code, 400)

    def test_legacy_default_export_keeps_old_scope_and_values(self):
        from sales.tests.export_helpers import legacy_export_sheet
        self.login_admin()
        kept, _ = self.make_order()
        cancelled, _ = self.make_order()
        SalesOrder.objects.filter(pk=cancelled.pk).update(status=SalesOrder.Status.CANCELLED)
        rows = list(legacy_export_sheet(self.client).iter_rows(values_only=True))
        self.assertEqual(rows[0], (*LEGACY_HEADERS, *[str(OrderOperationsProfile._meta.get_field(name).verbose_name)
                                                       for name in LEGACY_IMPORTED]))
        self.assertEqual([row[0] for row in rows[1:]], [kept.number])
        self.assertEqual(legacy_export_sheet(self.client, {"include_cancelled": "1"}).max_row, 3)
