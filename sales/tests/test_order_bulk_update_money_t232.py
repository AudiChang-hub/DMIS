"""T-232 第 3b 版：回匯開放金額欄位（成交車價、牌險、付款與分期、來源歸屬、收支人工金額）。

寫入跟訂單頁自動儲存同一段流程；預覽在交易裡試存再整筆退回，列出跟著重算的金額；逐張判斷鎖定；
多種付款方式的單不能改付款方式或車價。
"""
from decimal import Decimal

from django.contrib.auth import get_user_model

from sales.access.models import ScreenAccessGrant
from sales.models import OrderChange, OrderOperationsProfile, SalesOrder, SalesSource
from sales.order_exchange import reimport
from sales.tests.test_order_bulk_update_t232 import OrderBulkUpdateTests as BulkBase
from sales.tests.test_order_workspace import form_data, formset_data


class OrderBulkUpdateMoneyTests(BulkBase):
    # 只跑這一類新增的測試，不重跑 3a 的整組（基底的 test_* 由 3a 測試檔負責）。
    for _name in [name for name in dir(BulkBase) if name.startswith("test_")]:
        locals()[_name] = None
    del _name

    def test_vehicle_price_matches_autosave_and_preview_lists_recalculated_amounts(self):
        from django.urls import reverse
        from sales.forms import OrderEditForm, OrderPageAccessoryFormSet, OrderPageOtherFeeFormSet
        by_page, _ = self.make_order()
        by_file, _ = self.make_order()
        data = {**form_data(OrderEditForm(instance=by_page)),
                **formset_data(OrderPageAccessoryFormSet(instance=by_page, form_kwargs={"allow_manual": True})),
                **formset_data(OrderPageOtherFeeFormSet(instance=by_page, prefix="other_fees")),
                "_order_revision": str(by_page.revision), "_workspace": "1", "vehicle_price": "80000"}
        self.assertEqual(self.client.post(reverse("order_edit", args=[by_page.pk]), data, HTTP_X_ORDER_WORKSPACE="1").status_code, 200)

        book = self.export_book(["vehicle_price"])
        self.set_cell(book, by_file, "vehicle_price", 80000)
        batch = self.uploaded_batch(book)
        item = self.row_of(self.preview(batch), by_file)
        self.assertEqual([f["key"] for f in item["fields"]], ["vehicle_price"])
        balance = next(metric for metric in item["recalc"] if metric["label"] == "尾款")
        self.assertNotEqual(balance["before"], balance["after"])
        # 預覽的試算整筆退回：沒有留下任何修改。
        self.assertFalse(OrderChange.objects.filter(order=by_file).exists())
        self.assertEqual(SalesOrder.objects.get(pk=by_file.pk).vehicle_price, Decimal("75000"))

        self.apply(batch)
        page, bulk = SalesOrder.objects.get(pk=by_page.pk), SalesOrder.objects.get(pk=by_file.pk)
        self.assertEqual(bulk.vehicle_price, Decimal("80000"))
        for name in ("vehicle_price", "actual_balance", "calculated_balance", "payment_type"):
            self.assertEqual(getattr(bulk, name), getattr(page, name), name)
        self.assertEqual(OrderChange.objects.filter(order=bulk).latest("pk").changes,
                         OrderChange.objects.filter(order=page).latest("pk").changes)
        self.assertEqual(balance["after"], f"{bulk.actual_balance:,.0f}")

    def test_finance_manual_amount_becomes_manual_like_the_order_page(self):
        order, _vehicle = self.make_order()
        book = self.export_book(["gift_expense", "plate_selection_expense"])
        self.set_cell(book, order, "gift_expense", 1200)
        self.set_cell(book, order, "plate_selection_expense", 300)
        batch = self.uploaded_batch(book)
        item = self.row_of(self.preview(batch), order)
        self.assertEqual(item["validation"], [])
        self.assertIn("總支出", [metric["label"] for metric in item["recalc"]])
        self.apply(batch)
        profile = OrderOperationsProfile.objects.get(order=order)
        self.assertEqual((profile.gift_expense, profile.plate_selection_expense), (Decimal("1200"), Decimal("300")))
        # 跟收支頁相同：只有 MANUAL_PROTECTABLE_FINANCIAL_FIELDS 裡的欄位改了會標成人工值、之後不被系統重算蓋掉。
        self.assertIn("plate_selection_expense", profile.manual_financial_fields)
        self.assertNotIn("gift_expense", profile.manual_financial_fields)
        self.assertTrue(OrderChange.objects.filter(order=order, reason__startswith="批次修改").exists())

    def test_single_payment_type_rewrites_the_one_split(self):
        order, _vehicle = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(payment_splits=[{"method": "cash", "amount": 75000}])
        book = self.export_book(["payment_type"])
        self.set_cell(book, order, "payment_type", "刷卡")
        self.apply(self.uploaded_batch(book))
        order.refresh_from_db()
        self.assertEqual(order.payment_type, SalesOrder.PaymentType.CARD)
        self.assertEqual(order.payment_splits, [{"method": "card", "amount": 75000}])

    def test_multiple_payment_methods_cannot_change_payment_or_price(self):
        order, _vehicle = self.make_order()
        splits = [{"method": "cash", "amount": 40000}, {"method": "card", "amount": 35000}]
        SalesOrder.objects.filter(pk=order.pk).update(payment_splits=splits)
        book = self.export_book(["payment_type", "vehicle_price"])
        self.set_cell(book, order, "payment_type", "現金")
        self.set_cell(book, order, "vehicle_price", 90000)
        batch = self.uploaded_batch(book)
        item = self.row_of(self.preview(batch), order)
        self.assertEqual(item["fields"], [])
        self.assertEqual({entry["reason"] for entry in item["ignored"]}, {reimport.IGNORED_MULTI_PAYMENT})
        self.apply(batch)
        order.refresh_from_db()
        self.assertEqual(order.payment_splits, splits)

    def test_locked_finance_field_is_ignored_per_order(self):
        order, _vehicle = self.make_order()
        # 已有撥款快照（對帳入帳過）的單，實際車價收入在收支頁是停用的。
        OrderOperationsProfile.objects.filter(order=order).update(payment_disbursement_snapshot={"amount": "70000"})
        book = self.export_book(["actual_disbursement"])
        self.set_cell(book, order, "actual_disbursement", 1)
        item = self.row_of(self.preview(self.uploaded_batch(book)), order)
        self.assertEqual(item["fields"], [])
        self.assertEqual(item["ignored"][0]["reason"], reimport.IGNORED_LOCKED)

    def test_source_is_matched_by_name(self):
        order, _vehicle = self.make_order(dealer=True)
        other = SalesSource.objects.create(name="名稱對應車行", source_type=SalesOrder.SourceType.DEALER)
        book = self.export_book(["source"])
        self.set_cell(book, order, "source", "名稱對應車行")
        self.apply(self.uploaded_batch(book))
        order.refresh_from_db()
        self.assertEqual(order.source, other)

        book = self.export_book(["source"])
        self.set_cell(book, order, "source", "不存在的車行")
        item = self.row_of(self.preview(self.uploaded_batch(book)), order)
        self.assertTrue(any("找不到名稱「不存在的車行」" in message for message in item["errors"]))

    def test_finance_section_needs_order_finance(self):
        order, _vehicle = self.make_order()
        self.staff(("orders", {"operate": True, "export": True}), ("work", {"operate": True}),
                   ("order_finance", {}), ("order_bulk_update", {"operate": True}))
        user = get_user_model().objects.get(username="bulk-staff")
        self.assertFalse(ScreenAccessGrant.objects.get(user=user, screen_key="order_finance").operate)
        self.client.force_login(self.admin)  # 沒有收支權限的人匯不出收支欄，改用管理者匯出的檔
        book = self.export_book(["gift_expense"])
        self.set_cell(book, order, "gift_expense", 500)
        batch = self.uploaded_batch(book)
        batch.created_by = user
        batch.save(update_fields=["created_by"])
        self.client.force_login(user)
        item = self.row_of(self.preview(batch), order)
        self.assertIn("你沒有「收入與支出」的操作權限，這一區的欄位不能修改。", item["errors"])
