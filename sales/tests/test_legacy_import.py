from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl.styles import Font
from openpyxl import Workbook, load_workbook

from sales.models import (
    LegacyImportBatch,
    LegacyImportCorrection,
    LegacyImportMasterMapping,
    LegacyImportRow,
    LegacySalesSnapshot,
    SalesOrder,
    SalesSource,
    SalesSourceBrandPolicy,
    SalesSourceCooperationProfile,
    SalesSourceCategory,
    Store,
    VehicleColor,
    VehicleInventory,
    VehicleModel,
)
from sales.forms import LegacyImportRowCorrectionForm, LegacyImportUploadForm
from sales.jobs import run_legacy_import_job
from sales.services.legacy_import import (
    EMAIL_DROPPED_MESSAGE,
    INVALID_EMAIL_MESSAGE,
    PREVIEW_SCHEMA_VERSION,
    _clean_sales_source_name,
    _infer_sales_transaction_type,
    _infer_sales_vehicle_category,
    _sales_order_note,
    apply_import_row_decision,
    build_import_master_workspace,
    build_import_preview,
    ignore_all_unmapped,
    restore_ignored_mapping,
    unresolved_master_count,
    confirm_import,
    file_sha256,
    revalidate_import_batch,
    retry_completed_import_row,
    save_import_master_mapping,
)


# 與目前實際使用的 Excel 銷貨頁籤第 3 列表頭一致（只有欄位名稱，沒有任何客戶資料）。
SALES_SHEET_HEADERS = (
    "序號", "領牌日期", "車種型號", "油：引擎號碼、電：車身號碼",
    "車主名稱", "顏色", "收款價", "成本",
    "月份", "現金", "信用卡", "信用卡手續費支出",
    "分期手續費支出", "領牌稅金支出", "強制險支出", "選號支出",
    "中古車支出", "贈品、運費支出", "車行傭金支出", "友善車行獎金支出",
    "首賣獎金支出", "台數獎金支出", "領牌稅金收入", "強制險收入",
    "代辦費收入", "報廢代辦收入", "選號收入", "中古車收入",
    "報廢車收入", "手續費收入", "山葉獎金收入", "友善車行獎金收入",
    "其他收入", "實銷獎勵金", "促銷補助金", "分期補貼息",
    "強制險傭金", "信用卡傭金", "單筆淨利", "車行",
    "車行收款", "分期公司", "期數", "領牌日期2",
    "車牌號碼", "車主名稱2", "生日", "民國生日",
    "身分證字號", "戶籍地址", "手機", "Email",
    "工業局發票號碼", "發票日期", "尾款發票號碼", "補助方案",
    "補助金額", "銀行", "匯款帳戶", "申請日",
    "工業局", "環境部", "縣市政府", "舊車車主",
    "舊車車主身分證", "舊車牌照號碼", "舊車引擎號碼", "舊車廠牌",
    "排氣量", "出廠日期", "報廢日期", "回收日期",
    "舊車戶籍", "舊車車主電話", "車控帳號", "車控密碼",
    "電池合約方案", "電池合約啟用日期", "電池合約帳號", "電池合約密碼",
    "安全帽", "公司禮卷、匯款", "其他", "平台贈品",
    "欄1", "備註", "訂單日期", "公司贈品",
    "客服電話", "分期資訊", "特殊方案", "領牌年月",
)


def workbook_bytes(kind="operations"):
    workbook = Workbook()
    if kind == "operations":
        sales = workbook.active
        sales.title = "銷貨"
        for column, label in enumerate(SALES_SHEET_HEADERS, 1):
            sales.cell(3, column, label)
        sales["B4"] = "2026/08/01"
        sales["C4"] = "TEST125"
        sales["D4"] = " ab-123 "
        sales["E4"] = "舊欄姓名"
        sales["AT4"] = "正式車主"
        sales["F4"] = "白"
        sales["G4"] = 70000
        sales["H4"] = 60000
        sales["J4"] = 70000
        sales["AS4"] = "ABC-1234"
        sales["AW4"] = "A123456789"
        sales["AX4"] = "新北市測試路1號"
        sales["AY4"] = "0912345678"
        sales["CI4"] = "2026/07/30"
        inventory = workbook.create_sheet("進貨")
        for column, label in enumerate(("進貨日期", "車種型號", "車身號碼", "顏色", "尺碼", "數量", "單價", "總額", "月份", "出廠日期"), 1):
            inventory.cell(1, column, label)
        inventory.append(["2026/07/01", "TEST125", " AB-123 ", "白", "", 0, "", "", "", "2026/06"])
    else:
        dealer = workbook.active
        dealer.title = "車行"
        dealer.append(["", "", "", "", "", "", "", "月餅", "價格表", "容量"])
        dealer.append(["店名", "負責人", "電話一", "電話二", "手機", "傳真", "地址", "三陽", "台鈴", "排車容量", "備註"])
        dealer.append(["測試車行", "王先生", "02-1234", "", "0912", "", "新北市", "", "V", 5, "合作中"])
        platform = workbook.create_sheet("網路平台")
        platform.append(["平台", "聯絡人", "電話", "分機", "手機", "信箱"])
        platform.append(["測試平台", "李小姐", "02-5678", "123", "", "test@example.com"])
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def conflict_workbook_bytes():
    workbook = load_workbook(BytesIO(workbook_bytes()))
    inventory = workbook["進貨"]
    inventory.append(["2026/07/02", "TEST125", "AB 123", "黑", "", 1, "", "", "", "2026/07"])
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def used_vehicle_resale_workbook_bytes(mark_as_used=True):
    workbook = load_workbook(BytesIO(workbook_bytes()))
    sales = workbook["銷貨"]
    sales["AN3"] = "車行"
    sales["AT3"] = "車主名稱2"
    sales["AW3"] = "身分證字號"
    sales["B5"] = "2026/08/05"
    sales["C5"] = "TEST125"
    sales["D5"] = "AB-123"
    sales["E5"] = "中古車主"
    sales["AT5"] = "中古車主"
    sales["F5"] = "白"
    sales["G5"] = 30000
    sales["J5"] = 30000
    sales["AN5"] = "中古車" if mark_as_used else ""
    sales["AS5"] = "ABC-1234"
    sales["AW5"] = "B223456789"
    sales["AX5"] = "新北市中古路2號"
    sales["AY5"] = "0987654321"
    # 舊 Excel 尾端常因公式留下只有 0 的空白列，不能產生假訂單。
    sales["AT6"] = 0
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


class LegacyImportTests(TestCase):
    def test_deleted_import_is_not_recreated_by_stale_row_commit(self):
        from sales.services.order_deletion import change_deletion, confirmation_token
        from sales.services.legacy_import import _commit_sales_row
        batch = self.make_batch("operations")
        build_import_preview(batch)
        confirm_import(batch, "tester")
        order = SalesOrder.objects.get()
        root = get_user_model().objects.create_superuser("admin", password="Synthetic-test-only-89!")
        change_deletion(user=root, order_id=order.pk, restore=False, force=True, reason="匯入錯誤",
            expected_updated_at=order.updated_at.isoformat(), confirmation=confirmation_token(order, root))
        repeated = self.make_batch("operations")
        build_import_preview(repeated)
        row = repeated.rows.get(sheet_name="銷貨")
        row.action = LegacyImportRow.Action.CREATE  # 模擬舊預覽／重試，不信任先前判定。
        _commit_sales_row(row, "tester")
        self.assertEqual(row.action, LegacyImportRow.Action.SKIP)
        self.assertEqual(SalesOrder.objects.count(), 0)
        self.assertEqual(SalesOrder.all_objects.count(), 1)

    def test_import_formation_date_and_full_finance_mapping(self):
        batch = self.make_batch(LegacyImportBatch.ImportType.OPERATIONS)
        workbook = load_workbook(BytesIO(workbook_bytes()))
        sheet = workbook["銷貨"]
        sheet["AM3"], sheet["AM4"] = "單筆淨利", 9573.936
        sheet["L3"], sheet["L4"] = "信用卡手續費支出", 426.064
        stream = BytesIO()
        workbook.save(stream)
        batch.source_file.save("formation-finance.xlsx", SimpleUploadedFile("formation-finance.xlsx", stream.getvalue()))
        build_import_preview(batch)
        confirm_import(batch, "tester")
        order = SalesOrder.objects.get()
        from datetime import date
        from decimal import Decimal
        self.assertEqual(order.established_on, date(2026, 8, 1))
        self.assertEqual(order.order_date, date(2026, 7, 30))
        self.assertEqual(order.operations.net_profit, Decimal("9574"))  # 金額一律存整數
        self.assertEqual(order.operations.legacy_finance_reconciliation["status"], "matched")

    def keep_unmapped_masters(self, batch):
        """測試用：把預覽裡待補的車型與通路都標為保留歷史文字，模擬使用者已處理主檔。"""
        from sales.models import LegacyImportMasterMapping
        for kind in (LegacyImportMasterMapping.MappingType.VEHICLE_MODEL, LegacyImportMasterMapping.MappingType.SALES_SOURCE):
            from sales.services.legacy_import import _unresolved_master_values
            values = _unresolved_master_values(batch, kind)
            if values:
                ignore_all_unmapped(batch, kind, "tester", len(values))
        batch.refresh_from_db()

    def source_workbook(self, *names):
        workbook = load_workbook(BytesIO(workbook_bytes()))
        workbook["銷貨"]["AN4"] = names[0] if names else ""
        return workbook

    def test_confirm_is_blocked_until_masters_are_resolved(self):
        from sales.models import LegacyImportMasterMapping
        batch = self.batch_from_workbook(self.source_workbook("新合作車行"))
        build_import_preview(batch)
        batch.refresh_from_db()
        self.assertEqual(unresolved_master_count(batch), 2)  # 車型 TEST125、來源 新合作車行
        page = self.client.get(reverse("legacy_import_detail", args=[batch.pk]))
        self.assertContains(page, "處理 2 個待補主檔")
        self.assertNotContains(page, "確認匯入 ")
        with patch("sales.views.django_rq.get_queue") as get_queue:
            response = self.client.post(reverse("legacy_import_confirm", args=[batch.pk]))
            self.assertRedirects(response, reverse("legacy_import_detail", args=[batch.pk]) + "#master-data-workspace")
            get_queue.return_value.enqueue.assert_not_called()
        batch.refresh_from_db()
        self.assertEqual(batch.status, LegacyImportBatch.Status.PREVIEW)
        self.assertFalse(SalesOrder.objects.exists())
        self.keep_unmapped_masters(batch)
        self.assertEqual(unresolved_master_count(batch), 0)
        page = self.client.get(reverse("legacy_import_detail", args=[batch.pk]))
        self.assertContains(page, "確認匯入 ")
        self.assertContains(page, "待補主檔都處理完了")
        self.assertEqual(
            LegacyImportMasterMapping.objects.filter(ignored=True, note="整批保留歷史文字").count(), 2
        )

    def test_bulk_keep_only_touches_unresolved_values_and_checks_the_count(self):
        from sales.models import LegacyImportMasterMapping
        batch = self.batch_from_workbook(self.source_workbook("新合作車行"))
        build_import_preview(batch)
        batch.refresh_from_db()
        kind = LegacyImportMasterMapping.MappingType.SALES_SOURCE
        with self.assertRaisesMessage(ValueError, "沒有保留任何項目"):
            ignore_all_unmapped(batch, kind, "tester", 5)  # 使用者確認的個數與目前不同
        self.assertFalse(LegacyImportMasterMapping.objects.exists())
        self.assertEqual(ignore_all_unmapped(batch, kind, "tester", 1), 1)
        mapping = LegacyImportMasterMapping.objects.get()
        self.assertTrue(mapping.ignored)
        self.assertEqual((mapping.mapping_type, mapping.source_value, mapping.updated_by), (kind, "新合作車行", "tester"))
        batch.refresh_from_db()
        self.assertEqual(unresolved_master_count(batch), 1)  # 車型沒被動到
        with self.assertRaisesMessage(ValueError, "目前沒有待處理"):
            ignore_all_unmapped(batch, kind, "tester", 0)

    def test_values_differing_only_in_case_count_once(self):
        from sales.models import LegacyImportMasterMapping
        from sales.services.legacy_import import _unresolved_master_values
        batch = self.batch_from_workbook(self.source_workbook())
        build_import_preview(batch)
        batch.preview_summary = {**batch.preview_summary, "validation": {
            **batch.preview_summary["validation"], "unmapped_sources": ["Yahoo", "yahoo", "momo"]}}
        batch.save(update_fields=["preview_summary"])
        kind = LegacyImportMasterMapping.MappingType.SALES_SOURCE
        self.assertEqual(len(_unresolved_master_values(batch, kind)), 2)

    def test_bulk_keep_through_the_page_and_restore_a_mistake(self):
        batch = self.batch_from_workbook(self.source_workbook("新合作車行"))
        build_import_preview(batch)
        url = reverse("legacy_import_master_resolve", args=[batch.pk, "sales_source"])
        stale = self.client.post(url, {"resolution_action": "ignore_all", "expected_count": "9"})
        self.assertRedirects(stale, reverse("legacy_import_detail", args=[batch.pk]) + "#master-data-workspace")
        batch.refresh_from_db()
        self.assertEqual(unresolved_master_count(batch), 2)
        ok = self.client.post(url, {"resolution_action": "ignore_all", "expected_count": "1"}, follow=True)
        self.assertContains(ok, "已將其餘 1 個通路全部保留為歷史文字")
        self.assertContains(ok, "已保留歷史文字的項目")
        self.assertContains(ok, "新合作車行")
        batch.refresh_from_db()
        self.assertEqual(unresolved_master_count(batch), 1)
        restored = self.client.post(
            reverse("legacy_import_master_restore", args=[batch.pk, "sales_source"]),
            {"source_value": "新合作車行"}, follow=True)
        self.assertContains(restored, "已將「新合作車行」改回待處理")
        batch.refresh_from_db()
        self.assertEqual(unresolved_master_count(batch), 2)
        again = self.client.post(
            reverse("legacy_import_master_restore", args=[batch.pk, "sales_source"]),
            {"source_value": "新合作車行"}, follow=True)
        self.assertContains(again, "找不到這個已保留的項目")

    def test_restore_is_refused_after_the_import_has_started(self):
        batch = self.batch_from_workbook(self.source_workbook("新合作車行"))
        build_import_preview(batch)
        self.keep_unmapped_masters(batch)
        LegacyImportBatch.objects.filter(pk=batch.pk).update(status=LegacyImportBatch.Status.COMPLETED)
        batch.refresh_from_db()
        with self.assertRaises(ValueError):
            restore_ignored_mapping(batch, "sales_source", "新合作車行")

    def upload_through_page(self, sheets, kind="operations"):
        data = {"import_type": kind, "source_file": SimpleUploadedFile(
            "sheets.xlsx", workbook_bytes(kind),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        if sheets is not None:
            data["sheets"] = sheets
        response = self.client.post(reverse("legacy_import_list"), data)
        return response, LegacyImportBatch.objects.order_by("-created_at").first()

    def test_upload_can_pick_sales_sheet_only_and_inventory_is_not_read(self):
        response, batch = self.upload_through_page(["銷貨"])
        self.assertRedirects(response, reverse("legacy_import_detail", args=[batch.pk]))
        sheets = set(batch.rows.values_list("sheet_name", flat=True))
        self.assertEqual(sheets, {"銷貨"})
        self.assertEqual(batch.preview_summary["selected_sheets"], ["銷貨"])
        self.assertEqual(batch.preview_summary["errors"], {})  # 沒選進貨就不會提示「找不到進貨工作表」
        self.assertTrue(batch.preview_summary["validation"]["inventory_skipped"])
        page = self.client.get(reverse("legacy_import_detail", args=[batch.pk]))
        self.assertContains(page, "本批次只匯入：銷貨")
        self.assertContains(page, "本批次不匯入進貨")
        self.assertNotContains(page, "系統有、Excel 無")
        self.keep_unmapped_masters(batch)
        confirm_import(batch, "tester")
        order = SalesOrder.objects.get()
        self.assertIsNone(order.allocated_vehicle_id)
        self.assertEqual(VehicleInventory.objects.count(), 0)
        self.assertEqual(order.legacy_snapshot.vehicle_identifier.strip().upper(), "AB-123")

    def test_upload_default_imports_both_sheets_like_before(self):
        response, batch = self.upload_through_page(["銷貨", "進貨"])
        self.assertEqual(set(batch.rows.values_list("sheet_name", flat=True)), {"銷貨", "進貨"})
        self.assertEqual(batch.preview_summary["selected_sheets"], ["進貨", "銷貨"])
        self.assertFalse(batch.preview_summary["validation"]["inventory_skipped"])
        page = self.client.get(reverse("legacy_import_detail", args=[batch.pk]))
        self.assertNotContains(page, "本批次只匯入")
        self.assertContains(page, "系統有、Excel 無")
        form_page = self.client.get(reverse("legacy_import_list"))
        self.assertContains(form_page, 'name="sheets"')
        self.assertContains(form_page, "checked")

    def test_upload_requires_at_least_one_sheet_for_operations_but_not_for_channels(self):
        before = LegacyImportBatch.objects.count()
        response, _ = self.upload_through_page(None)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "請至少選一個要匯入的頁籤")
        self.assertEqual(LegacyImportBatch.objects.count(), before)
        response, batch = self.upload_through_page(None, kind="channels")
        self.assertEqual(LegacyImportBatch.objects.count(), before + 1)
        self.assertEqual(batch.preview_summary["selected_sheets"], [])

    def test_sheet_choice_survives_revalidation_and_old_batches_mean_both(self):
        from sales.services.legacy_import import selected_operations_sheets
        _, batch = self.upload_through_page(["銷貨"])
        batch.refresh_from_db()
        revalidate_import_batch(batch)
        batch.refresh_from_db()
        self.assertEqual(selected_operations_sheets(batch), ["銷貨"])
        self.assertTrue(batch.preview_summary["validation"]["inventory_skipped"])
        batch.preview_summary = {}
        self.assertEqual(selected_operations_sheets(batch), ["進貨", "銷貨"])

    def test_inventory_only_selection_is_allowed(self):
        _, batch = self.upload_through_page(["進貨"])
        self.assertEqual(set(batch.rows.values_list("sheet_name", flat=True)), {"進貨"})
        self.assertEqual(batch.preview_summary["errors"], {})

    def batch_from_workbook(self, workbook, name="header-mapping.xlsx"):
        stream = BytesIO()
        workbook.save(stream)
        upload = SimpleUploadedFile(name, stream.getvalue())
        return LegacyImportBatch.objects.create(
            import_type=LegacyImportBatch.ImportType.OPERATIONS,
            source_file=upload,
            original_filename=name,
            file_sha256=file_sha256(upload),
            file_size=len(stream.getvalue()),
            uploaded_by="tester",
        )

    def test_columns_are_read_by_header_name_not_position(self):
        workbook = load_workbook(BytesIO(workbook_bytes()))
        sales = workbook["銷貨"]
        sales["AY4"] = "0912345678"
        # 在最前面與中間各插入新欄：所有欄位位置都往右移，結果必須和原本完全相同。
        sales.insert_cols(1)
        sales["A3"] = "新增欄"
        sales.insert_cols(30)
        sales.cell(3, 30, "另一個新增欄")
        batch = self.batch_from_workbook(workbook)
        build_import_preview(batch)
        confirm_import(batch, "tester")
        order = SalesOrder.objects.get()
        self.assertEqual(order.owner_name, "正式車主")
        self.assertEqual(order.owner_phone, "0912345678")
        self.assertEqual(order.owner_id_number, "A123456789")
        self.assertEqual(order.final_plate_number, "ABC-1234")
        self.assertEqual(order.order_date.isoformat(), "2026-07-30")
        self.assertEqual(batch.preview_summary["blocking"], {})

    def test_missing_required_header_blocks_confirmation(self):
        workbook = load_workbook(BytesIO(workbook_bytes()))
        workbook["銷貨"]["C3"] = None
        batch = self.batch_from_workbook(workbook)
        build_import_preview(batch)
        batch.refresh_from_db()
        self.assertIn("車種型號", batch.preview_summary["blocking"]["銷貨"])
        self.assertEqual(batch.rows.filter(sheet_name="銷貨").count(), 0)
        with self.assertRaisesMessage(ValueError, "表頭"):
            confirm_import(batch, "tester")
        page = self.client.get(reverse("legacy_import_detail", args=[batch.pk]))
        self.assertContains(page, "找不到必要表頭：車種型號")
        self.assertEqual(SalesOrder.objects.count(), 0)

    def test_older_header_names_are_accepted_and_missing_optional_headers_warn(self):
        workbook = load_workbook(BytesIO(workbook_bytes()))
        sales = workbook["銷貨"]
        sales["CM3"] = "銷售方案分類"  # 舊版 Excel 的欄名
        sales["CM4"] = "試乘車"
        sales["CJ3"] = None
        batch = self.batch_from_workbook(workbook)
        build_import_preview(batch)
        batch.refresh_from_db()
        row = batch.rows.get(sheet_name="銷貨")
        self.assertEqual(row.mapped_data["sales_category"], "試乘車")
        self.assertEqual(row.mapped_data["transaction_type"], SalesOrder.TransactionType.TEST_RIDE)
        self.assertTrue(any("公司贈品" in warning for warning in batch.preview_summary["warnings"]))
        page = self.client.get(reverse("legacy_import_detail", args=[batch.pk]))
        self.assertContains(page, "表頭提醒")
        self.assertContains(page, "找不到表頭：公司贈品")

    def test_bank_and_account_are_placed_by_content_even_when_headers_are_swapped(self):
        from sales.services.legacy_import import _split_bank_and_account
        for first, second, expected in (
            ("299540972331", "中國信託", ("中國信託", "299540972331", False)),  # 目前 Excel 的常見放法
            ("0131092國泰世華銀行汐止分行", "12345678901", ("0131092國泰世華銀行汐止分行", "12345678901", False)),
            ("00113990812591", "700汐止社后郵局", ("700汐止社后郵局", "00113990812591", False)),
            ("", "", ("", "", False)),
            ("中國信託", "", ("中國信託", "", False)),
            ("", "123-456-789", ("", "123-456-789", False)),
            ("中國信託", "玉山銀行", ("中國信託", "玉山銀行", True)),
            ("123456789", "987654321", ("123456789", "987654321", True)),
        ):
            with self.subTest(first=first, second=second):
                self.assertEqual(_split_bank_and_account(first, second), expected)
        workbook = load_workbook(BytesIO(workbook_bytes()))
        sales = workbook["銷貨"]
        sales["BF4"], sales["BG4"] = "299540972331", "中國信託基隆分行"
        batch = self.batch_from_workbook(workbook)
        build_import_preview(batch)
        confirm_import(batch, "tester")
        profile = SalesOrder.objects.get().operations
        self.assertEqual(profile.bank_name, "中國信託基隆分行")
        self.assertEqual(profile.remittance_account, "299540972331")

    def test_unclear_bank_account_row_is_flagged_for_review(self):
        from sales.services.legacy_import import BANK_ACCOUNT_UNCLEAR_MESSAGE
        workbook = load_workbook(BytesIO(workbook_bytes()))
        sales = workbook["銷貨"]
        sales["BF4"], sales["BG4"] = "中國信託", "玉山銀行"
        batch = self.batch_from_workbook(workbook)
        build_import_preview(batch)
        row = batch.rows.get(sheet_name="銷貨")
        self.assertIn(BANK_ACCOUNT_UNCLEAR_MESSAGE, row.messages)

    def test_subsidy_old_vehicle_and_fulfillment_columns_are_imported_but_passwords_are_not(self):
        from datetime import date
        workbook = load_workbook(BytesIO(workbook_bytes()))
        sales = workbook["銷貨"]
        values = {
            "E4": "舊欄姓名", "AT4": "車主甲", "AW4": "A123456789",
            "BL4": "車主甲", "BM4": None, "BN4": "XUR-616", "BO4": "SA20EC-107475",
            "BP4": "光陽", "BQ4": 101, "BR4": "200509", "BS4": "2026/06/24", "BT4": "2026/06/25",
            "BW4": "airlin88", "BX4": "secret-control-password", "BY4": "499吃到飽", "BZ4": "2026/08/02",
            "CA4": "battery-account", "CB4": "secret-battery-password",
            "CD4": "郵政禮卷5000元", "CE4": "行車紀錄器", "CF4": "3000統一禮券", "CJ4": "座墊",
            "CK4": "客服電話：02-8953-8686", "CL4": "分期和潤 18期，每期 3000",
            "BI4": "V", "BJ4": "已寄出", "BK4": "12/29=53000",
        }
        for cell, value in values.items():
            sales[cell] = value
        sales["BL4"] = "車主甲"
        batch = self.batch_from_workbook(workbook)
        build_import_preview(batch)
        confirm_import(batch, "tester")
        order = SalesOrder.objects.get()
        profile = order.operations
        self.assertTrue(order.old_owner_same_as_owner)
        self.assertEqual(order.old_owner_name, "車主甲")
        self.assertEqual(order.old_owner_id_number, "A123456789")
        self.assertEqual(order.trade_in_plate, "XUR-616")
        self.assertEqual(profile.old_vehicle_engine_number, "SA20EC-107475")
        self.assertEqual(profile.old_vehicle_brand, "光陽")
        self.assertEqual(profile.old_vehicle_displacement_cc, 101)
        self.assertEqual(profile.old_vehicle_manufactured_on, date(2005, 9, 1))
        self.assertEqual(profile.scrapped_on, date(2026, 6, 24))
        self.assertEqual(profile.recycled_on, date(2026, 6, 25))
        self.assertEqual(profile.vehicle_control_account, "airlin88")
        self.assertEqual(profile.battery_plan, "499吃到飽")
        self.assertEqual(profile.battery_activated_on, date(2026, 8, 2))
        self.assertEqual(profile.battery_account, "battery-account")
        self.assertEqual(profile.company_gift_or_remittance, "郵政禮卷5000元")
        self.assertEqual(profile.platform_gift, "3000統一禮券")
        self.assertIn("行車紀錄器", profile.other_fulfillment)
        self.assertIn("公司贈品：座墊", profile.other_fulfillment)
        self.assertEqual(profile.customer_service_phone, "客服電話：02-8953-8686")
        self.assertEqual(profile.installment_info, "分期和潤 18期，每期 3000")
        # 密碼不從 Excel 匯入，原始值也不得出現在任何已存欄位。
        self.assertEqual(profile.vehicle_control_password_encrypted, "")
        self.assertEqual(profile.battery_password_encrypted, "")
        stored = " ".join(str(value) for value in profile.__dict__.values())
        self.assertNotIn("secret-control-password", stored)
        self.assertNotIn("secret-battery-password", stored)

    def test_zero_left_by_excel_formulas_is_not_imported_as_text(self):
        workbook = load_workbook(BytesIO(workbook_bytes()))
        sales = workbook["銷貨"]
        for cell in ("BL4", "BM4", "BN4", "BP4", "CE4", "CK4"):
            sales[cell] = 0
        batch = self.batch_from_workbook(workbook)
        build_import_preview(batch)
        confirm_import(batch, "tester")
        order = SalesOrder.objects.get()
        self.assertEqual((order.old_owner_name, order.trade_in_plate), ("", ""))
        self.assertEqual(order.operations.old_vehicle_brand, "")
        self.assertEqual(order.operations.other_fulfillment, "")
        self.assertEqual(order.operations.customer_service_phone, "")

    def setUp(self):
        Store.objects.create(name="總店", code="MAIN")
        self.user = get_user_model().objects.create_user(username="importer", password="test-pass")
        self.client.force_login(self.user)
        from sales.tests.profit_helpers import unlock_profit
        unlock_profit(self, self.user)
        self.tempdir = TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.tempdir.name)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        self.tempdir.cleanup()

    def make_batch(self, kind):
        content = workbook_bytes(kind)
        upload = SimpleUploadedFile(f"{kind}.xlsx", content)
        digest = file_sha256(upload)
        return LegacyImportBatch.objects.create(
            import_type=kind,
            source_file=upload,
            original_filename=f"{kind}.xlsx",
            file_sha256=digest,
            file_size=len(content),
            uploaded_by="tester",
        )

    def make_conflict_batch(self):
        content = conflict_workbook_bytes()
        upload = SimpleUploadedFile("conflicts.xlsx", content)
        digest = file_sha256(upload)
        return LegacyImportBatch.objects.create(
            import_type=LegacyImportBatch.ImportType.OPERATIONS,
            source_file=upload,
            original_filename="conflicts.xlsx",
            file_sha256=digest,
            file_size=len(content),
            uploaded_by="tester",
        )

    def make_used_vehicle_batch(self, mark_as_used=True):
        content = used_vehicle_resale_workbook_bytes(mark_as_used=mark_as_used)
        upload = SimpleUploadedFile("used-vehicle.xlsx", content)
        digest = file_sha256(upload)
        return LegacyImportBatch.objects.create(
            import_type=LegacyImportBatch.ImportType.OPERATIONS,
            source_file=upload,
            original_filename="used-vehicle.xlsx",
            file_sha256=digest,
            file_size=len(content),
            uploaded_by="tester",
        )

    def test_upload_form_only_contains_type_and_file(self):
        self.assertEqual(list(LegacyImportUploadForm().fields), ["import_type", "source_file", "sheets"])

    def make_review_row(self, changes=None):
        batch = self.make_batch(LegacyImportBatch.ImportType.OPERATIONS)
        build_import_preview(batch)
        confirm_import(batch, "tester")
        original = batch.rows.get(sheet_name="銷貨")
        row = LegacyImportRow.objects.create(
            batch=batch, sheet_name="銷貨", source_row=1752,
            fingerprint="review-only", natural_key="review-only",
            action=LegacyImportRow.Action.ERROR, raw_data={},
            mapped_data={**original.mapped_data, **(changes or {})},
            messages=["allocated_vehicle：包含 已配車輛 的 銷售訂單 已經存在。"],
        )
        return row, SalesOrder.objects.get(pk=original.committed_pk)

    def test_import_review_date_change_focus_and_three_way_comparison(self):
        row, order = self.make_review_row({"registration_date": "2026-08-15"})
        before = list(SalesOrder.objects.values())
        form = LegacyImportRowCorrectionForm(row=row)
        comparison = form.review["comparisons"][0]
        self.assertIn("改期", comparison["title"])
        field = next(value for value in comparison["values"] if value["key"] == "registration_date")
        self.assertEqual((field["previous"], field["current"], field["incoming"]), ("2026-08-01", "2026-08-01", "2026-08-15"))
        self.assertEqual(form.fields["registration_date"].widget.attrs["data-import-review-primary"], "true")
        self.assertNotIn("allocated_vehicle", form.review["messages"][0])
        response = self.client.get(reverse("legacy_import_detail", args=[row.batch_id]), {"action": "error", "edit": row.pk})
        self.assertContains(response, "import-review-field--highlight")
        self.assertContains(response, "上次匯入的 Excel")
        self.assertContains(response, order.number)
        self.assertContains(response, 'id_registration_date_review')
        self.assertEqual(before, list(SalesOrder.objects.values()))
        row.refresh_from_db()
        self.assertEqual(row.action, LegacyImportRow.Action.ERROR)
        self.assertFalse(row.corrections.exists())

    def test_import_review_changed_buyer_is_not_a_duplicate_or_automatic_cancel(self):
        row, order = self.make_review_row({"owner_name": '<script>alert("test")</script>'})
        form = LegacyImportRowCorrectionForm(row=row)
        self.assertIn("換買家", form.review["comparisons"][0]["title"])
        self.assertEqual(form.fields["owner_name"].widget.attrs["data-import-review-primary"], "true")
        response = self.client.get(reverse("legacy_import_detail", args=[row.batch_id]), {"edit": row.pk})
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, '<script>alert("test")</script>')
        order.refresh_from_db()
        self.assertEqual(order.owner_name, "正式車主")
        self.assertEqual(order.status, SalesOrder.Status.COMPLETED)

    def test_import_review_normalized_identifier_and_same_major_fields(self):
        row, order = self.make_review_row({"identifier_raw": "ab 123"})
        form = LegacyImportRowCorrectionForm(row=row)
        self.assertIn("疑似重複", form.review["comparisons"][0]["title"])
        self.assertIn("仍須核對收支", form.review["comparisons"][0]["guidance"])
        self.assertEqual(form.review["comparisons"][0]["order"], order)

    def test_import_review_keeps_current_and_historical_values_separate(self):
        row, order = self.make_review_row({"registration_date": "2026-08-15"})
        SalesOrder.objects.filter(pk=order.pk).update(registration_date="2026-08-20")
        comparison = LegacyImportRowCorrectionForm(row=row).review["comparisons"][0]
        field = next(value for value in comparison["values"] if value["key"] == "registration_date")
        self.assertEqual((field["previous"], field["current"], field["incoming"]), ("2026-08-01", "2026-08-20", "2026-08-15"))

    def test_import_review_no_snapshot_and_different_vehicle_not_matched(self):
        row, order = self.make_review_row()
        LegacySalesSnapshot.objects.filter(order=order).delete()
        form = LegacyImportRowCorrectionForm(row=row)
        self.assertIsNone(form.review["comparisons"][0]["previous_row"])
        row.mapped_data["identifier_raw"] = "NOT-THIS-VEHICLE"
        self.assertEqual(LegacyImportRowCorrectionForm(row=row).review["comparisons"], [])

    def test_import_review_unknown_error_is_not_assigned_to_random_field(self):
        batch = self.make_batch(LegacyImportBatch.ImportType.OPERATIONS)
        build_import_preview(batch)
        row = batch.rows.get(sheet_name="銷貨")
        row.messages = ["來源暫時無法讀取"]
        form = LegacyImportRowCorrectionForm(row=row)
        self.assertEqual(form.review["notes"], {})
        self.assertEqual(form.review["messages"], row.messages)
        row.messages = ["owner_email：電子郵件格式不正確"]
        form = LegacyImportRowCorrectionForm(row=row)
        self.assertIn("data-import-review-primary", form.fields["owner_email"].widget.attrs)

    def test_import_review_id_difference_and_all_vehicle_categories_visible(self):
        row, order = self.make_review_row({"owner_id_number": "B223456789"})
        form = LegacyImportRowCorrectionForm(row=row)
        self.assertIn("換買家", form.review["comparisons"][0]["title"])
        self.assertIn("owner_id_number", form.review["notes"])
        row.mapped_data["vehicle_category"] = SalesOrder.VehicleCategory.USED
        self.assertEqual(LegacyImportRowCorrectionForm(row=row).review["comparisons"][0]["order"], order)

    def test_import_review_lists_all_orders_beyond_five_and_peer_rows(self):
        row, original = self.make_review_row()
        for index in range(6):
            archived = SalesOrder.objects.create(owner_name=f"歷史買家{index}", owner_id_number=f"HIST-REVIEW-{index}",
                owner_phone="未提供", owner_address="未提供", vehicle_model=original.vehicle_model, color=original.color,
                vehicle_category=SalesOrder.VehicleCategory.USED, status=SalesOrder.Status.CANCELLED)
            peer = LegacyImportRow.objects.create(batch=row.batch, sheet_name="銷貨", source_row=1800+index,
                fingerprint=f"peer-{index}", natural_key=f"peer-{index}", action="create", mapped_data=original.legacy_snapshot.import_row.mapped_data,
                committed_model="SalesOrder", committed_pk=str(archived.pk))
            LegacySalesSnapshot.objects.create(order=archived, import_row=peer, vehicle_identifier="AB-123")
        review = LegacyImportRowCorrectionForm(row=row).review
        self.assertEqual(len(review["comparisons"]), 7)
        self.assertEqual(sum(item["occupies_vehicle"] for item in review["comparisons"]), 1)
        self.assertGreaterEqual(len(review["peer_rows"]), 7)
        response = self.client.get(reverse("legacy_import_detail", args=[row.batch_id]), {"edit": row.pk})
        for index in range(6):
            self.assertContains(response, f"歷史買家{index}")
        self.assertContains(response, "目前配車占用")
        self.assertContains(response, "全部相關訂單")

    def test_inventory_review_does_not_infer_buyer_cancellation(self):
        row, order = self.make_review_row()
        inventory = row.batch.rows.get(sheet_name="進貨")
        comparison = LegacyImportRowCorrectionForm(row=inventory).review["comparisons"][0]
        self.assertEqual(comparison["order"], order)
        self.assertIn("核對庫存", comparison["title"])
        self.assertNotIn("換買家", comparison["title"])

    def test_invalid_row_can_be_excluded_without_filling_required_import_fields(self):
        batch = self.make_batch(LegacyImportBatch.ImportType.OPERATIONS)
        build_import_preview(batch)
        row = batch.rows.get(sheet_name="進貨")
        form = LegacyImportRowCorrectionForm(
            {"decision": "exclude", "reason": "來源列無法確認，先不匯入"},
            row=row,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_operations_preview_and_confirm_preserves_historical_price(self):
        batch = self.make_batch(LegacyImportBatch.ImportType.OPERATIONS)
        summary = build_import_preview(batch)
        self.assertEqual(summary["source_rows"], 2)
        self.assertEqual(batch.rows.filter(sheet_name="銷貨").count(), 1)
        result = confirm_import(batch, "tester")
        self.assertEqual(result["created"], 2)
        order = SalesOrder.objects.get(owner_name="正式車主")
        self.assertEqual(order.vehicle_price, 0)
        self.assertEqual(order.allocated_vehicle.normalized_engine_number, "AB123")
        self.assertEqual(order.legacy_snapshot.historical_received_price, 70000)
        self.assertEqual(LegacySalesSnapshot.objects.count(), 1)
        self.assertEqual(VehicleInventory.objects.get().status, VehicleInventory.Status.SOLD)

    def test_trial_vehicle_source_suffix_becomes_order_note(self):
        SalesSource.objects.create(
            name="昌勝",
            source_type=SalesSource.SourceType.DEALER,
            active=True,
        )
        workbook = load_workbook(BytesIO(workbook_bytes()))
        workbook["銷貨"]["AN3"] = "車行"
        workbook["銷貨"]["AN4"] = "昌勝(試乘車)"
        stream = BytesIO()
        workbook.save(stream)
        upload = SimpleUploadedFile("trial-vehicle.xlsx", stream.getvalue())
        batch = LegacyImportBatch.objects.create(
            import_type=LegacyImportBatch.ImportType.OPERATIONS,
            source_file=upload,
            original_filename="trial-vehicle.xlsx",
            file_sha256=file_sha256(upload),
            file_size=len(stream.getvalue()),
            uploaded_by="tester",
        )

        build_import_preview(batch)
        sales_row = batch.rows.get(sheet_name="銷貨")
        self.assertEqual(sales_row.mapped_data["dealer_name"], "昌勝")
        self.assertEqual(sales_row.mapped_data["transaction_type"], "test_ride")
        self.assertEqual(sales_row.mapped_data["note"], "試乘車")

        confirm_import(batch, "tester")

        order = SalesOrder.objects.get(owner_name="正式車主")
        self.assertEqual(order.source.name, "昌勝")
        self.assertEqual(order.transaction_type, SalesOrder.TransactionType.TEST_RIDE)
        self.assertEqual(order.note, "試乘車")

    def test_subsidy_application_pseudo_source_becomes_order_note(self):
        workbook = load_workbook(BytesIO(workbook_bytes()))
        workbook["銷貨"]["AN3"] = "車行"
        workbook["銷貨"]["AN4"] = "代申請補助"
        stream = BytesIO()
        workbook.save(stream)
        upload = SimpleUploadedFile("subsidy-application.xlsx", stream.getvalue())
        batch = LegacyImportBatch.objects.create(
            import_type=LegacyImportBatch.ImportType.OPERATIONS,
            source_file=upload,
            original_filename="subsidy-application.xlsx",
            file_sha256=file_sha256(upload),
            file_size=len(stream.getvalue()),
            uploaded_by="tester",
        )

        build_import_preview(batch)
        sales_row = batch.rows.get(sheet_name="銷貨")
        self.assertEqual(sales_row.mapped_data["dealer_name"], "")
        self.assertEqual(sales_row.mapped_data["transaction_type"], "regular_new")
        self.assertEqual(sales_row.mapped_data["note"], "代申請補助")

        confirm_import(batch, "tester")

        order = SalesOrder.objects.get(owner_name="正式車主")
        self.assertIsNone(order.source)
        self.assertEqual(order.source_type, SalesOrder.SourceType.STORE)
        self.assertEqual(
            order.transaction_type, SalesOrder.TransactionType.REGULAR_NEW
        )
        self.assertEqual(order.note, "代申請補助")
        self.assertEqual(order.operations.dealer_name, "")

    def test_invalid_email_is_dropped_but_row_still_imports(self):
        workbook = load_workbook(BytesIO(workbook_bytes()))
        workbook["銷貨"]["AZ4"] = "新北市測試路1號"
        stream = BytesIO()
        workbook.save(stream)
        upload = SimpleUploadedFile("invalid-email.xlsx", stream.getvalue())
        batch = LegacyImportBatch.objects.create(
            import_type=LegacyImportBatch.ImportType.OPERATIONS,
            source_file=upload,
            original_filename="invalid-email.xlsx",
            file_sha256=file_sha256(upload),
            file_size=len(stream.getvalue()),
            uploaded_by="tester",
        )

        summary = build_import_preview(batch)

        sales_row = batch.rows.get(sheet_name="銷貨")
        self.assertEqual(sales_row.action, LegacyImportRow.Action.CREATE)
        self.assertIn(EMAIL_DROPPED_MESSAGE, sales_row.messages)
        self.assertEqual(sales_row.mapped_data["owner_email"], "")
        self.assertEqual(summary["counts"]["error"], 0)
        confirm_import(batch, "tester")
        order = SalesOrder.objects.get()
        self.assertEqual(order.owner_email, "")
        self.assertEqual(order.owner_phone, "0912345678")  # 其他資料照常匯入
        self.assertEqual(order.owner_name, "正式車主")

    @patch("sales.views.django_rq.get_queue")
    def test_confirm_starts_background_import_and_status_endpoint_reports_progress(self, get_queue):
        batch = self.make_batch(LegacyImportBatch.ImportType.OPERATIONS)
        build_import_preview(batch)
        self.keep_unmapped_masters(batch)
        get_queue.return_value.enqueue.return_value.id = "job-123"

        response = self.client.post(reverse("legacy_import_confirm", args=[batch.pk]))

        self.assertRedirects(response, reverse("legacy_import_detail", args=[batch.pk]))
        batch.refresh_from_db()
        self.assertEqual(batch.status, LegacyImportBatch.Status.PROCESSING)
        self.assertEqual(batch.processing_total, 2)
        self.assertEqual(batch.processing_job_id, "job-123")
        self.assertFalse(SalesOrder.objects.exists())
        get_queue.return_value.enqueue.assert_called_once()

        status_response = self.client.get(reverse("legacy_import_status", args=[batch.pk]))
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.json()["status"], "processing")
        self.assertEqual(status_response.json()["percent"], 0)

        run_legacy_import_job(str(batch.pk), "tester")
        batch.refresh_from_db()
        self.assertEqual(batch.status, LegacyImportBatch.Status.COMPLETED)
        self.assertEqual(batch.processing_completed, 2)
        self.assertEqual(SalesOrder.objects.count(), 1)

    @patch("sales.views.django_rq.get_queue")
    def test_duplicate_confirm_does_not_enqueue_second_job(self, get_queue):
        batch = self.make_batch(LegacyImportBatch.ImportType.OPERATIONS)
        build_import_preview(batch)
        self.keep_unmapped_masters(batch)
        get_queue.return_value.enqueue.return_value.id = "job-123"

        self.client.post(reverse("legacy_import_confirm", args=[batch.pk]))
        self.client.post(reverse("legacy_import_confirm", args=[batch.pk]))

        get_queue.return_value.enqueue.assert_called_once()

    @patch("sales.views.django_rq.get_queue")
    def test_enqueue_failure_returns_batch_to_preview(self, get_queue):
        batch = self.make_batch(LegacyImportBatch.ImportType.OPERATIONS)
        build_import_preview(batch)
        self.keep_unmapped_masters(batch)
        get_queue.return_value.enqueue.side_effect = RuntimeError("redis unavailable")

        self.client.post(reverse("legacy_import_confirm", args=[batch.pk]))

        batch.refresh_from_db()
        self.assertEqual(batch.status, LegacyImportBatch.Status.PREVIEW)
        self.assertIn("無法啟動", batch.processing_error)
        self.assertFalse(SalesOrder.objects.exists())

    def test_failed_background_import_can_resume_without_duplicate_records(self):
        batch = self.make_batch(LegacyImportBatch.ImportType.OPERATIONS)
        build_import_preview(batch)
        confirm_import(batch, "tester")
        batch.refresh_from_db()
        batch.status = LegacyImportBatch.Status.FAILED
        batch.processing_error = "模擬 worker 中斷"
        batch.save(update_fields=["status", "processing_error", "updated_at"])

        result = confirm_import(batch, "tester")

        self.assertEqual(result["created"], 2)
        self.assertEqual(SalesOrder.objects.count(), 1)
        self.assertEqual(VehicleInventory.objects.count(), 1)

    def test_completed_error_row_can_be_repaired_and_imported_alone(self):
        workbook = load_workbook(BytesIO(workbook_bytes()))
        workbook["銷貨"]["AZ4"] = "0912345678"
        stream = BytesIO()
        workbook.save(stream)
        upload = SimpleUploadedFile("repair-email.xlsx", stream.getvalue())
        batch = LegacyImportBatch.objects.create(
            import_type=LegacyImportBatch.ImportType.OPERATIONS,
            source_file=upload,
            original_filename="repair-email.xlsx",
            file_sha256=file_sha256(upload),
            file_size=len(stream.getvalue()),
            uploaded_by="tester",
        )
        build_import_preview(batch)
        sales_row = batch.rows.get(sheet_name="銷貨")
        apply_import_row_decision(
            sales_row,
            {},
            LegacyImportCorrection.Decision.EXCLUDE,
            "先完成其他資料",
            "tester",
        )
        confirm_import(batch, "tester")
        sales_row.refresh_from_db()
        sales_row.action = LegacyImportRow.Action.ERROR
        sales_row.excluded = False
        sales_row.messages = [INVALID_EMAIL_MESSAGE]
        sales_row.save(update_fields=["action", "excluded", "messages", "updated_at"])
        batch.refresh_from_db()
        batch.result_summary = {**batch.result_summary, "excluded": 0, "errors": 1}
        batch.save(update_fields=["result_summary", "updated_at"])

        result = retry_completed_import_row(
            sales_row,
            {"owner_email": ""},
            LegacyImportCorrection.Decision.CORRECT,
            "Email 欄誤放電話，清空後補匯",
            "tester",
        )

        self.assertTrue(result["ok"])
        sales_row.refresh_from_db()
        batch.refresh_from_db()
        self.assertEqual(sales_row.committed_model, "SalesOrder")
        self.assertEqual(SalesOrder.objects.count(), 1)
        self.assertEqual(batch.result_summary["errors"], 0)

    def test_explicit_used_vehicle_signals_do_not_match_trade_in_wording(self):
        self.assertEqual(
            _infer_sales_vehicle_category({}, "中古車")[0],
            SalesOrder.VehicleCategory.USED,
        )
        self.assertEqual(
            _infer_sales_vehicle_category({"備註": "中古車買賣"}, "")[0],
            SalesOrder.VehicleCategory.USED,
        )
        self.assertEqual(
            _infer_sales_vehicle_category({"補助方案": "FUN 中古車過戶"}, "")[0],
            SalesOrder.VehicleCategory.USED,
        )
        self.assertEqual(
            _infer_sales_vehicle_category({"備註": "新車成交，另有中古車估價"}, "")[0],
            SalesOrder.VehicleCategory.NEW,
        )

    def test_transaction_type_is_separated_from_sales_source_name(self):
        self.assertEqual(_clean_sales_source_name("昌勝(試乘車)"), "昌勝")
        self.assertEqual(_clean_sales_source_name("東永-試乘車"), "東永")
        self.assertEqual(_clean_sales_source_name("中獎車"), "")
        self.assertEqual(_clean_sales_source_name("代申請補助"), "")
        self.assertEqual(
            _clean_sales_source_name("昌勝(代申請補助)"), "昌勝"
        )
        self.assertEqual(
            _infer_sales_transaction_type(
                {}, "昌勝(試乘車)", SalesOrder.VehicleCategory.NEW
            )[0],
            SalesOrder.TransactionType.TEST_RIDE,
        )
        self.assertEqual(
            _infer_sales_transaction_type(
                {}, "中獎車", SalesOrder.VehicleCategory.NEW
            )[0],
            SalesOrder.TransactionType.PRIZE,
        )
        self.assertEqual(
            _infer_sales_transaction_type(
                {}, "中古車", SalesOrder.VehicleCategory.USED
            )[0],
            SalesOrder.TransactionType.USED,
        )
        self.assertEqual(
            _sales_order_note(
                {}, "昌勝(試乘車)", SalesOrder.TransactionType.TEST_RIDE
            ),
            "試乘車",
        )
        self.assertEqual(
            _sales_order_note(
                {"備註": "客戶指定"},
                "昌勝（試乘車）",
                SalesOrder.TransactionType.TEST_RIDE,
                "試乘車",
            ),
            "試乘車\n客戶指定",
        )
        self.assertEqual(
            _sales_order_note(
                {},
                "代申請補助",
                SalesOrder.TransactionType.REGULAR_NEW,
            ),
            "代申請補助",
        )

    def test_special_platform_source_name_is_moved_to_order_note(self):
        rules = (
            ("momo員購", "momo"),
            ("小樹購員購", "小樹購"),
            ("Yahoo+假展場", "Yahoo"),
        )
        for legacy_name, canonical_name in rules:
            with self.subTest(legacy_name=legacy_name):
                self.assertEqual(
                    _clean_sales_source_name(legacy_name), canonical_name
                )
                self.assertEqual(
                    _sales_order_note(
                        {},
                        legacy_name,
                        SalesOrder.TransactionType.REGULAR_NEW,
                    ),
                    legacy_name,
                )

    def test_employee_purchase_platform_name_is_moved_to_store_order_note(self):
        source_names = (
            "上海商銀員購",
            "台新銀員購",
            "台新銀行員購",
            "華新麗華員購",
        )
        for source_name in source_names:
            with self.subTest(source_name=source_name):
                self.assertEqual(_clean_sales_source_name(source_name), "")
                self.assertEqual(
                    _sales_order_note(
                        {},
                        source_name,
                        SalesOrder.TransactionType.REGULAR_NEW,
                    ),
                    source_name,
                )
                self.assertEqual(
                    _sales_order_note(
                        {"備註": source_name},
                        source_name,
                        SalesOrder.TransactionType.REGULAR_NEW,
                        source_name,
                    ),
                    source_name,
                )

        self.assertEqual(_clean_sales_source_name("博客來"), "博客來")
        self.assertEqual(
            _sales_order_note(
                {}, "博客來", SalesOrder.TransactionType.REGULAR_NEW
            ),
            "",
        )

    def test_used_vehicle_resale_can_share_identifier_without_reusing_inventory(self):
        batch = self.make_used_vehicle_batch()
        summary = build_import_preview(batch)
        self.assertEqual(summary["counts"]["conflict"], 0)
        self.assertEqual(summary["validation"]["used_vehicle_sales"], 1)
        sales_rows = list(batch.rows.filter(sheet_name="銷貨").order_by("source_row"))
        self.assertEqual(len(sales_rows), 2)
        self.assertEqual(sales_rows[0].mapped_data["vehicle_category"], "new")
        self.assertEqual(sales_rows[1].mapped_data["vehicle_category"], "used")
        self.assertNotEqual(sales_rows[0].natural_key, sales_rows[1].natural_key)

        confirm_import(batch, "tester")

        new_order = SalesOrder.objects.get(owner_name="正式車主")
        used_order = SalesOrder.objects.get(owner_name="中古車主")
        self.assertEqual(new_order.vehicle_category, SalesOrder.VehicleCategory.NEW)
        self.assertIsNotNone(new_order.allocated_vehicle)
        self.assertEqual(used_order.vehicle_category, SalesOrder.VehicleCategory.USED)
        self.assertIsNone(used_order.allocated_vehicle)
        self.assertEqual(used_order.legacy_snapshot.vehicle_identifier, "AB-123")
        self.assertIn("ab123", used_order.search_index.search_text)
        detail = self.client.get(reverse("order_detail", args=[used_order.pk]))
        self.assertContains(detail, "歷史中古車交易")
        self.assertContains(detail, "不需占用新車庫存")

    def test_revalidate_backfills_vehicle_category_for_existing_preview(self):
        batch = self.make_used_vehicle_batch()
        build_import_preview(batch)
        for row in batch.rows.filter(sheet_name="銷貨"):
            mapped_data = dict(row.mapped_data)
            mapped_data.pop("vehicle_category", None)
            mapped_data.pop("vehicle_category_reason", None)
            row.mapped_data = mapped_data
            row.save(update_fields=["mapped_data", "updated_at"])
        placeholder = LegacyImportRow.objects.create(
            batch=batch,
            sheet_name="銷貨",
            source_row=99,
            fingerprint="0" * 64,
            natural_key="legacy-placeholder",
            action=LegacyImportRow.Action.CREATE,
            raw_data={"車主名稱": 0},
            mapped_data={
                "owner_name": "0",
                "model_number": "",
                "identifier": "",
                "plate_number": "",
            },
            messages=[],
        )

        summary = revalidate_import_batch(batch)

        rows = list(batch.rows.filter(sheet_name="銷貨").order_by("source_row"))
        self.assertEqual(summary["counts"]["conflict"], 0)
        self.assertEqual(summary["counts"]["skip"], 1)
        self.assertEqual(summary["validation"]["used_vehicle_sales"], 1)
        self.assertEqual(rows[0].mapped_data["vehicle_category"], "new")
        self.assertEqual(rows[1].mapped_data["vehicle_category"], "used")
        placeholder.refresh_from_db()
        self.assertEqual(placeholder.action, LegacyImportRow.Action.SKIP)
        self.assertIn("Excel 空白公式列，系統自動略過", placeholder.messages)

    def test_opening_old_preview_automatically_applies_current_parser_rules(self):
        batch = self.make_batch(LegacyImportBatch.ImportType.OPERATIONS)
        build_import_preview(batch)
        row = batch.rows.get(sheet_name="銷貨")
        mapped_data = dict(row.mapped_data)
        mapped_data["dealer_name"] = "試乘車"
        mapped_data["dealer_name_raw"] = "試乘車"
        mapped_data["transaction_type"] = SalesOrder.TransactionType.REGULAR_NEW
        mapped_data["transaction_type_reason"] = "舊版預設值"
        row.mapped_data = mapped_data
        row.save(update_fields=["mapped_data", "updated_at"])
        batch.preview_summary = {
            **batch.preview_summary,
            "validation": {"unmapped_sources": ["試乘車"]},
        }
        batch.preview_summary.pop("parser_schema_version", None)
        batch.save(update_fields=["preview_summary", "updated_at"])

        response = self.client.get(reverse("legacy_import_detail", args=[batch.pk]))

        self.assertEqual(response.status_code, 200)
        row.refresh_from_db()
        batch.refresh_from_db()
        self.assertEqual(row.mapped_data["dealer_name_raw"], "試乘車")
        self.assertEqual(row.mapped_data["dealer_name"], "")
        self.assertEqual(
            row.mapped_data["transaction_type"],
            SalesOrder.TransactionType.TEST_RIDE,
        )
        self.assertEqual(
            batch.preview_summary["parser_schema_version"],
            PREVIEW_SCHEMA_VERSION,
        )
        self.assertNotIn(
            "試乘車", batch.preview_summary["validation"]["unmapped_sources"]
        )

    def test_ambiguous_second_new_sale_stays_conflict_until_marked_used(self):
        batch = self.make_used_vehicle_batch(mark_as_used=False)
        summary = build_import_preview(batch)
        self.assertEqual(summary["counts"]["conflict"], 2)
        later_row = batch.rows.filter(sheet_name="銷貨").order_by("source_row").last()
        mapping = dict(later_row.mapped_data)
        mapping["vehicle_category"] = SalesOrder.VehicleCategory.USED
        summary = apply_import_row_decision(
            later_row,
            mapping,
            LegacyImportCorrection.Decision.CORRECT,
            "確認為中古車交易",
            "tester",
        )
        later_row.refresh_from_db()
        self.assertEqual(summary["counts"]["conflict"], 0)
        self.assertEqual(later_row.mapped_data["vehicle_category_reason"], "人工調整")

    def test_channel_preview_groups_source_and_contact(self):
        batch = self.make_batch(LegacyImportBatch.ImportType.CHANNELS)
        summary = build_import_preview(batch)
        # 只讀「車行」工作表，「網路平台」工作表不匯入。
        self.assertEqual(summary["source_rows"], 1)
        result = confirm_import(batch, "tester")
        self.assertEqual(result["created"], 1)
        self.assertEqual(batch.rows.filter(committed_model="SalesSource").count(), 1)
        dealer = SalesSource.objects.get(name="測試車行")
        self.assertFalse(SalesSource.objects.filter(name="測試平台").exists())
        self.assertEqual(dealer.responsible_person, "王先生")
        self.assertEqual(dealer.phone, "02-1234")
        self.assertEqual(dealer.mobile, "0912")
        self.assertEqual(dealer.address, "新北市")
        self.assertEqual(dealer.note, "合作中")
        profiles = {
            profile.cooperation_scope: profile
            for profile in dealer.cooperation_profiles.all()
        }
        self.assertEqual(len(profiles), 3)
        self.assertTrue(
            profiles[SalesSourceBrandPolicy.CooperationScope.SUZUKI_GAS].cooperates
        )
        self.assertTrue(
            profiles[SalesSourceBrandPolicy.CooperationScope.SUZUKI_ELECTRIC].cooperates
        )
        self.assertFalse(
            profiles[SalesSourceBrandPolicy.CooperationScope.SYM].cooperates
        )
        self.assertIsNone(dealer.sym_vehicle_capacity)
        self.assertEqual(dealer.suzuki_vehicle_capacity, 5)

    def test_current_dealer_workbook_maps_suzuki_electric_without_gas(self):
        workbook = Workbook()
        dealer = workbook.active
        dealer.title = "車行"
        dealer.append(["月餅", "LINE群組", "", "", "", "", "", "", "", "價格表", "", "排車容量", "", ""])
        dealer.append(["", "", "店名", "負責人", "電話一", "電話二", "手機", "手機/傳真", "地址", "三陽", "台鈴", "三陽", "台鈴", "備註"])
        dealer.append(["", "E", "電動車行", "王先生", "02-1234", "", "0912", "", "基隆市仁愛區", "", "電動車", "", 3, "Excel 備註"])
        dealer.append(["", "", "油電車行", "李小姐", "02-5678", "", "0922", "", "新北市汐止區", "", "V", "", 5, "油電備註"])
        dealer.append(["", "", "已結束車行", "陳先生", "02-9999", "", "0933", "", "台北市", "", "V", "", 2, ""])
        dealer.cell(dealer.max_row, 3).font = Font(strike=True)
        workbook.create_sheet("網路平台").append(["平台", "聯絡人", "電話", "分機", "手機", "信箱"])
        stream = BytesIO()
        workbook.save(stream)
        upload = SimpleUploadedFile("channels-current.xlsx", stream.getvalue())
        batch = LegacyImportBatch.objects.create(
            import_type=LegacyImportBatch.ImportType.CHANNELS,
            source_file=upload,
            original_filename="channels-current.xlsx",
            file_sha256=file_sha256(upload),
            file_size=len(stream.getvalue()),
            uploaded_by="tester",
        )

        summary = build_import_preview(batch)
        self.assertIn("已結束車行", summary["notices"]["車行"])
        confirm_import(batch, "tester")
        # 店名有刪除線的列不匯入。
        self.assertFalse(SalesSource.objects.filter(name="已結束車行").exists())

        source = SalesSource.objects.get(name="電動車行")
        profiles = {
            item.cooperation_scope: item.cooperates
            for item in source.cooperation_profiles.all()
        }
        self.assertFalse(profiles[SalesSourceBrandPolicy.CooperationScope.SUZUKI_GAS])
        self.assertTrue(profiles[SalesSourceBrandPolicy.CooperationScope.SUZUKI_ELECTRIC])
        self.assertEqual(source.note, "Excel 備註")
        self.assertTrue(source.has_line_group)

        oil_and_electric = SalesSource.objects.get(name="油電車行")
        oil_and_electric_profiles = {
            item.cooperation_scope: item.cooperates
            for item in oil_and_electric.cooperation_profiles.all()
        }
        self.assertTrue(
            oil_and_electric_profiles[SalesSourceBrandPolicy.CooperationScope.SUZUKI_GAS]
        )
        self.assertTrue(
            oil_and_electric_profiles[SalesSourceBrandPolicy.CooperationScope.SUZUKI_ELECTRIC]
        )

    def test_same_batch_cannot_be_confirmed_twice(self):
        batch = self.make_batch(LegacyImportBatch.ImportType.CHANNELS)
        build_import_preview(batch)
        confirm_import(batch, "tester")
        with self.assertRaises(ValueError):
            confirm_import(batch, "tester")

    def test_unresolved_conflict_blocks_confirm(self):
        batch = self.make_conflict_batch()
        summary = build_import_preview(batch)
        self.assertEqual(summary["counts"]["conflict"], 2)
        with self.assertRaisesMessage(ValueError, "尚有 2 筆衝突或錯誤資料"):
            confirm_import(batch, "tester")
        self.assertFalse(SalesOrder.objects.exists())

    def test_correcting_identifier_revalidates_entire_batch_and_keeps_audit(self):
        batch = self.make_conflict_batch()
        build_import_preview(batch)
        row = batch.rows.filter(sheet_name="進貨").order_by("source_row").last()
        summary = apply_import_row_decision(
            row,
            {"identifier_raw": "AB-124"},
            LegacyImportCorrection.Decision.CORRECT,
            "第二筆識別號碼輸入錯誤",
            "tester",
        )
        row.refresh_from_db()
        self.assertEqual(summary["counts"]["conflict"], 0)
        self.assertEqual(row.mapped_data["identifier"], "AB124")
        self.assertTrue(row.manually_corrected)
        self.assertEqual(row.corrections.get().reason, "第二筆識別號碼輸入錯誤")

    def make_identifierless_batch(self, plates):
        workbook = load_workbook(BytesIO(workbook_bytes()))
        sales = workbook["銷貨"]
        sales["B4"] = sales["CI4"] = sales["D4"] = None
        sales["BB4"] = "2026/09/18"
        for offset, plate in enumerate(plates):
            row = 4 + offset
            for column in ("C", "E", "AT", "F", "G", "J", "AW", "AX", "AY", "BB"):
                sales[f"{column}{row}"] = sales[f"{column}4"].value
            sales[f"AS{row}"] = plate
        stream = BytesIO()
        workbook.save(stream)
        upload = SimpleUploadedFile("identifierless.xlsx", stream.getvalue())
        return LegacyImportBatch.objects.create(
            import_type=LegacyImportBatch.ImportType.OPERATIONS,
            source_file=upload,
            original_filename="identifierless.xlsx",
            file_sha256=file_sha256(upload),
            file_size=len(stream.getvalue()),
            uploaded_by="tester",
        )

    def test_identifierless_reimport_with_changed_plate_column_is_flagged(self):
        from datetime import date
        from sales.services.legacy_import import POSSIBLY_IMPORTED_SALES_MESSAGE
        first = self.make_identifierless_batch([None])
        build_import_preview(first)
        confirm_import(first, "tester")
        self.assertEqual(SalesOrder.objects.get().order_date, date(2026, 9, 18))
        # 車牌欄被填入備註，交易鍵改變，仍須視為疑似已匯入。
        repeated = self.make_identifierless_batch(["保險要富邦"])
        build_import_preview(repeated)
        row = repeated.rows.get(sheet_name="銷貨")
        self.assertEqual(row.action, LegacyImportRow.Action.CONFLICT)
        self.assertIn(POSSIBLY_IMPORTED_SALES_MESSAGE, row.messages)
        with self.assertRaises(ValueError):
            confirm_import(repeated, "tester")
        self.assertEqual(SalesOrder.objects.count(), 1)

    def test_identifierless_rows_differing_only_by_plate_in_same_sheet_conflict(self):
        from sales.services.legacy_import import DUPLICATE_SALES_TRANSACTION_MESSAGE
        batch = self.make_identifierless_batch([None, "保險要富邦"])
        build_import_preview(batch)
        rows = list(batch.rows.filter(sheet_name="銷貨"))
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row.action, LegacyImportRow.Action.CONFLICT)
            self.assertIn(DUPLICATE_SALES_TRANSACTION_MESSAGE, row.messages)

    def test_excluding_duplicate_resolves_conflict_without_changing_source(self):
        batch = self.make_conflict_batch()
        build_import_preview(batch)
        row = batch.rows.filter(sheet_name="進貨").order_by("source_row").last()
        original_raw = dict(row.raw_data)
        summary = apply_import_row_decision(
            row,
            {},
            LegacyImportCorrection.Decision.EXCLUDE,
            "Excel 重複列",
            "tester",
        )
        row.refresh_from_db()
        self.assertEqual(summary["counts"]["conflict"], 0)
        self.assertEqual(summary["counts"]["exclude"], 1)
        self.assertEqual(row.raw_data, original_raw)
        result = confirm_import(batch, "tester")
        self.assertEqual(result["excluded"], 1)

    def test_conflict_workspace_renders_and_row_can_be_corrected_in_browser_flow(self):
        batch = self.make_conflict_batch()
        build_import_preview(batch)
        conflict_url = reverse("legacy_import_detail", args=[batch.pk]) + "?action=conflict"
        response = self.client.get(conflict_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "重複資料比較")
        self.assertContains(response, "2 筆需要確認")
        row = batch.rows.filter(sheet_name="進貨").order_by("source_row").last()
        edit_response = self.client.get(conflict_url + f"&edit={row.pk}")
        self.assertEqual(edit_response.status_code, 200)
        self.assertContains(edit_response, "修正或排除此列")
        post_response = self.client.post(
            reverse("legacy_import_row_decide", args=[batch.pk, row.pk]),
            {
                "decision": "correct",
                "received_on": "2026-07-02",
                "model_number": "TEST125",
                "identifier_raw": "AB-124",
                "color": "黑",
                "quantity": "1",
                "manufactured_year_month": "2026/07",
                "reason": "識別號碼更正",
            },
        )
        self.assertEqual(post_response.status_code, 302)
        batch.refresh_from_db()
        self.assertEqual(batch.preview_summary["counts"]["conflict"], 0)

    def test_unmapped_vehicle_can_link_existing_master_without_changing_excel(self):
        batch = self.make_batch(LegacyImportBatch.ImportType.OPERATIONS)
        build_import_preview(batch)
        original_raw = dict(batch.rows.get(sheet_name="進貨").raw_data)
        target = VehicleModel.objects.create(
            brand="SUZUKI",
            name="SUI 125",
            model_number="UQ125DA",
            energy_type=VehicleModel.EnergyType.GAS,
            model_year=2026,
            model_code=VehicleModel.ModelType.FRONT_DISC_REAR_DRUM,
            displacement_cc=125,
        )
        response = self.client.post(
            reverse(
                "legacy_import_master_resolve",
                args=[batch.pk, LegacyImportMasterMapping.MappingType.VEHICLE_MODEL],
            ),
            {
                "source_value": "TEST125",
                "resolution_action": "link",
                "model-link-vehicle_model": target.pk,
            },
        )
        self.assertEqual(response.status_code, 302)
        batch.refresh_from_db()
        self.assertEqual(batch.preview_summary["validation"]["unmapped_models"], [])
        mapping = LegacyImportMasterMapping.objects.get()
        self.assertEqual(mapping.vehicle_model, target)
        self.assertEqual(batch.rows.get(sheet_name="進貨").raw_data, original_raw)

        confirm_import(batch, "tester")
        self.assertEqual(VehicleInventory.objects.get().vehicle_model, target)
        self.assertEqual(SalesOrder.objects.get().vehicle_model, target)

    def test_quick_create_source_and_mapping_are_reused_by_next_batch(self):
        content = workbook_bytes()
        workbook = load_workbook(BytesIO(content))
        workbook["銷貨"]["AN4"] = "新合作車行"
        stream = BytesIO()
        workbook.save(stream)
        payload = stream.getvalue()
        batch = LegacyImportBatch.objects.create(
            import_type=LegacyImportBatch.ImportType.OPERATIONS,
            source_file=SimpleUploadedFile("source.xlsx", payload),
            original_filename="source.xlsx",
            file_sha256="1" * 64,
            file_size=len(payload),
            uploaded_by="tester",
        )
        build_import_preview(batch)
        self.assertEqual(
            batch.preview_summary["validation"]["unmapped_sources"],
            ["新合作車行"],
        )
        response = self.client.post(
            reverse(
                "legacy_import_master_resolve",
                args=[batch.pk, LegacyImportMasterMapping.MappingType.SALES_SOURCE],
            ),
            {
                "source_value": "新合作車行",
                "resolution_action": "create",
                "source-create-source_category": SalesSourceCategory.objects.get(
                    name="合作車行"
                ).pk,
                "source-create-name": "新合作車行",
                "source-create-address": "新北市測試路",
            },
        )
        self.assertEqual(response.status_code, 302)
        source = SalesSource.objects.get(name="新合作車行")
        self.assertEqual(source.category.name, "合作車行")
        self.assertEqual(source.source_type, SalesSource.SourceType.DEALER)
        batch.refresh_from_db()
        self.assertEqual(batch.preview_summary["validation"]["unmapped_sources"], [])

        second = LegacyImportBatch.objects.create(
            import_type=LegacyImportBatch.ImportType.OPERATIONS,
            source_file=SimpleUploadedFile("source-2.xlsx", payload),
            original_filename="source-2.xlsx",
            file_sha256="2" * 64,
            file_size=len(payload),
            uploaded_by="tester",
        )
        summary = build_import_preview(second)
        self.assertEqual(summary["validation"]["unmapped_sources"], [])
        confirm_import(second, "tester")
        order = SalesOrder.objects.get()
        self.assertEqual(order.source, source)
        self.assertEqual(order.transaction_type, SalesOrder.TransactionType.REGULAR_NEW)

    def test_quick_create_can_add_staff_category_inline(self):
        content = workbook_bytes()
        workbook = load_workbook(BytesIO(content))
        workbook["銷貨"]["AN4"] = "文傑"
        stream = BytesIO()
        workbook.save(stream)
        payload = stream.getvalue()
        batch = LegacyImportBatch.objects.create(
            import_type=LegacyImportBatch.ImportType.OPERATIONS,
            source_file=SimpleUploadedFile("staff.xlsx", payload),
            original_filename="staff.xlsx",
            file_sha256="4" * 64,
            file_size=len(payload),
            uploaded_by="tester",
        )
        build_import_preview(batch)

        response = self.client.post(
            reverse(
                "legacy_import_master_resolve",
                args=[batch.pk, LegacyImportMasterMapping.MappingType.SALES_SOURCE],
            ),
            {
                "source_value": "文傑",
                "resolution_action": "create",
                "source-create-source_category": "",
                "source-create-new_category_name": "本店員工",
                "source-create-new_category_behavior": SalesSourceCategory.SystemBehavior.STORE,
                "source-create-name": "文傑",
                "source-create-address": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        source = SalesSource.objects.get(name="文傑")
        self.assertEqual(source.category.name, "本店員工")
        self.assertEqual(source.source_type, SalesSource.SourceType.STORE)

    def test_keep_historical_source_text_removes_warning_without_polluting_master(self):
        content = workbook_bytes()
        workbook = load_workbook(BytesIO(content))
        workbook["銷貨"]["AN4"] = "朋友推薦"
        stream = BytesIO()
        workbook.save(stream)
        payload = stream.getvalue()
        batch = LegacyImportBatch.objects.create(
            import_type=LegacyImportBatch.ImportType.OPERATIONS,
            source_file=SimpleUploadedFile("referral.xlsx", payload),
            original_filename="referral.xlsx",
            file_sha256="3" * 64,
            file_size=len(payload),
            uploaded_by="tester",
        )
        build_import_preview(batch)
        response = self.client.post(
            reverse(
                "legacy_import_master_resolve",
                args=[batch.pk, LegacyImportMasterMapping.MappingType.SALES_SOURCE],
            ),
            {
                "source_value": "朋友推薦",
                "resolution_action": "ignore",
                "note": "歷史分類文字，不是通路",
            },
        )
        self.assertEqual(response.status_code, 302)
        batch.refresh_from_db()
        self.assertEqual(batch.preview_summary["validation"]["unmapped_sources"], [])
        self.assertFalse(SalesSource.objects.filter(name="朋友推薦").exists())
        mapping = LegacyImportMasterMapping.objects.get()
        self.assertTrue(mapping.ignored)

    def test_master_workspace_shows_occurrence_count_and_observed_colors(self):
        batch = self.make_batch(LegacyImportBatch.ImportType.OPERATIONS)
        build_import_preview(batch)
        workspace = build_import_master_workspace(batch)
        self.assertEqual(workspace["total"], 1)
        self.assertEqual(workspace["models"][0]["source_value"], "TEST125")
        self.assertEqual(workspace["models"][0]["row_count"], 2)
        self.assertEqual(workspace["models"][0]["colors"], ["白"])
        self.assertEqual(len(workspace["models"][0]["examples"]), 2)
        sales_example = workspace["models"][0]["examples"][0]
        self.assertEqual(sales_example["context_label"], "新車銷售")
        self.assertEqual(sales_example["identifier"], "ab-123")
        self.assertEqual(sales_example["plate_number"], "ABC-1234")
        self.assertEqual(sales_example["owner_name"], "正式車主")
        response = self.client.get(reverse("legacy_import_detail", args=[batch.pk]))
        self.assertContains(response, "待補主檔工作台")
        self.assertContains(response, "Excel 出現 2 筆")
        self.assertContains(response, "查看車牌、車色與識別號碼")
        self.assertContains(response, "引擎／車身號碼")
        self.assertContains(response, "ABC-1234")

    def test_dr_z4sm_import_aliases_share_one_master_mapping(self):
        target = VehicleModel.objects.create(
            brand="SUZUKI",
            name="DR-Z4SM (滑胎版)",
            model_number="DR-Z4SM",
            energy_type=VehicleModel.EnergyType.GAS,
            model_year=2026,
            model_code=VehicleModel.ModelType.ABS_DUAL_DISC,
            displacement_cc=398,
        )

        save_import_master_mapping(
            mapping_type=LegacyImportMasterMapping.MappingType.VEHICLE_MODEL,
            source_value="DRZ-4SM",
            vehicle_model=target,
            actor_name="tester",
        )
        save_import_master_mapping(
            mapping_type=LegacyImportMasterMapping.MappingType.VEHICLE_MODEL,
            source_value="DR-Z4SM (滑胎版)",
            vehicle_model=target,
            actor_name="tester",
        )

        mapping = LegacyImportMasterMapping.objects.get()
        self.assertEqual(mapping.normalized_source_value, "dr-z4sm")
        self.assertEqual(mapping.vehicle_model_id, target.pk)

    def test_dr_z4s_import_aliases_share_one_master_mapping(self):
        target = VehicleModel.objects.create(
            brand="SUZUKI",
            name="DR-Z4S (越野版)",
            model_number="DR-Z4S",
            energy_type=VehicleModel.EnergyType.GAS,
            model_year=2026,
            model_code=VehicleModel.ModelType.ABS_DUAL_DISC,
            displacement_cc=398,
        )

        save_import_master_mapping(
            mapping_type=LegacyImportMasterMapping.MappingType.VEHICLE_MODEL,
            source_value="DRZ-4S",
            vehicle_model=target,
            actor_name="tester",
        )
        save_import_master_mapping(
            mapping_type=LegacyImportMasterMapping.MappingType.VEHICLE_MODEL,
            source_value="DR-Z4S",
            vehicle_model=target,
            actor_name="tester",
        )

        mapping = LegacyImportMasterMapping.objects.get()
        self.assertEqual(mapping.normalized_source_value, "dr-z4s")
        self.assertEqual(mapping.vehicle_model_id, target.pk)

    def test_preview_rows_search_by_linked_machine_model_number_and_identifier(self):
        batch = self.make_batch(LegacyImportBatch.ImportType.OPERATIONS)
        build_import_preview(batch)
        target = VehicleModel.objects.create(
            brand="SUZUKI",
            name="SUI 125",
            model_number="UQ125DA",
            energy_type=VehicleModel.EnergyType.GAS,
            model_year=2026,
            model_code=VehicleModel.ModelType.FRONT_DISC_REAR_DRUM,
        )
        save_import_master_mapping(
            mapping_type=LegacyImportMasterMapping.MappingType.VEHICLE_MODEL,
            source_value="TEST125",
            vehicle_model=target,
            actor_name="tester",
        )

        for query in ("SUI 125", "UQ125DA", "ab123"):
            with self.subTest(query=query):
                response = self.client.get(
                    reverse("legacy_import_detail", args=[batch.pk]),
                    {"q": query},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["page_obj"].paginator.count, 2)
                self.assertContains(response, "TEST125")

        empty = self.client.get(
            reverse("legacy_import_detail", args=[batch.pk]),
            {"q": "完全不存在"},
        )
        self.assertEqual(empty.context["page_obj"].paginator.count, 0)

    def test_shifted_contact_values_are_not_treated_as_vehicle_models(self):
        content = workbook_bytes()
        workbook = load_workbook(BytesIO(content))
        sales = workbook["銷貨"]
        sales["C5"] = "02"
        sales["D5"] = "26951112"
        sales["C6"] = "7000021"
        sales["D6"] = "usmartmotor@gmail.com"
        sales["C7"] = "RARE125"
        sales["D7"] = "CGA2-750464"
        stream = BytesIO()
        workbook.save(stream)
        payload = stream.getvalue()
        batch = LegacyImportBatch.objects.create(
            import_type=LegacyImportBatch.ImportType.OPERATIONS,
            source_file=SimpleUploadedFile("shifted-contact.xlsx", payload),
            original_filename="shifted-contact.xlsx",
            file_sha256="4" * 64,
            file_size=len(payload),
            uploaded_by="tester",
        )

        summary = build_import_preview(batch)

        self.assertEqual(summary["counts"]["skip"], 2)
        self.assertEqual(summary["validation"]["unmapped_models"], ["RARE125", "TEST125"])
        ignored_rows = batch.rows.filter(sheet_name="銷貨", source_row__in=[5, 6])
        self.assertEqual(ignored_rows.filter(action="skip").count(), 2)
        self.assertTrue(
            all(
                "缺少有效車輛序號且無交易資料，系統自動略過" in row.messages
                for row in ignored_rows
            )
        )
        workspace = build_import_master_workspace(batch)
        self.assertEqual(
            [item["source_value"] for item in workspace["models"]],
            ["RARE125", "TEST125"],
        )

    def test_preview_batch_can_be_deleted_with_uploaded_file(self):
        batch = self.make_batch(LegacyImportBatch.ImportType.CHANNELS)
        build_import_preview(batch)
        stored_path = Path(batch.source_file.path)
        self.assertTrue(stored_path.exists())
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("legacy_import_delete", args=[batch.pk]))
        self.assertRedirects(response, reverse("legacy_import_list"))
        self.assertFalse(LegacyImportBatch.objects.filter(pk=batch.pk).exists())
        self.assertFalse(stored_path.exists())

    def test_completed_batch_cannot_be_deleted_but_can_be_archived_and_restored(self):
        batch = self.make_batch(LegacyImportBatch.ImportType.CHANNELS)
        build_import_preview(batch)
        confirm_import(batch, "tester")
        delete_response = self.client.post(reverse("legacy_import_delete", args=[batch.pk]))
        self.assertEqual(delete_response.status_code, 302)
        self.assertTrue(LegacyImportBatch.objects.filter(pk=batch.pk).exists())
        self.client.post(reverse("legacy_import_archive", args=[batch.pk]))
        batch.refresh_from_db()
        self.assertIsNotNone(batch.archived_at)
        self.client.post(reverse("legacy_import_restore", args=[batch.pk]))
        batch.refresh_from_db()
        self.assertIsNone(batch.archived_at)

    def test_excluded_sales_row_is_not_treated_as_previously_imported_next_time(self):
        first = self.make_batch(LegacyImportBatch.ImportType.OPERATIONS)
        build_import_preview(first)
        sales_row = first.rows.get(sheet_name="銷貨")
        apply_import_row_decision(
            sales_row,
            {},
            LegacyImportCorrection.Decision.EXCLUDE,
            "本次先不匯入銷貨",
            "tester",
        )
        confirm_import(first, "tester")
        second = self.make_batch(LegacyImportBatch.ImportType.OPERATIONS)
        build_import_preview(second)
        self.assertEqual(
            second.rows.get(sheet_name="銷貨").action,
            "create",
        )
