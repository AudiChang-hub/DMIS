"""T-334 第一版：原廠代墊／代轉追蹤。

原廠活動的獎金或贈品，先給客人或車行、原廠之後補（代墊），或原廠先撥、再轉交（代轉）。左手進、右手出：
不算淨利、不動客戶應收、不擋交車。訂單頁、追蹤頁、營運總表側邊明細是同一份資料；權限比照能改「收入與支出」。
測試資料一律明顯虛構。
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import (ManufacturerAdvance, ManufacturerAdvancePayout, OrderEvent, OrderOperationsProfile, SalesOrder,
                          SalesSource, VehicleColor, VehicleModel)
from sales.services import manufacturer_advance as advances
from sales.services.finance_ledger import finance_totals
from sales.services.payment_summary import payment_summary

XHR = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


class AdvanceTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser("admin", password="Test-Only-123", first_name="測試主管")
        cls.dealer = SalesSource.objects.create(name="虛構車行乙", source_type="dealer")
        cls.model = VehicleModel.objects.create(brand="SUZUKI", name="虛構車型甲", energy_type="gas", base_dealer_commission=2000)
        cls.other_model = VehicleModel.objects.create(brand="SYM", name="虛構車型丙", energy_type="gas")
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="白")
        cls.other_color = VehicleColor.objects.create(vehicle_model=cls.other_model, name="黑")

    def setUp(self):
        self.client.force_login(self.admin)

    def make_order(self, **kwargs):
        fields = dict(
            source_type="dealer", source=self.dealer, order_date=date(2026, 9, 1), owner_type="company",
            owner_name="測試客戶甲", owner_id_number="83739807", owner_phone="0912345678", owner_address="測試地址",
            vehicle_model=self.model, color=self.color, vehicle_price=Decimal("79800"), plate_insurance_fee=Decimal("2350"),
            payment_type="cash", delivery_method="store_pickup",
        )
        fields.update(kwargs)
        order = SalesOrder(**fields)
        order.calculated_balance = order.calculate_balance()
        order.actual_balance = order.calculated_balance
        order.save()
        return order

    def add(self, order, **data):
        payload = {"manufacturer": "SUZUKI", "campaign_name": "虛構年終現金回饋", "recipient": "customer", "kind": "cash",
                   "amount": "1000", **data}
        response = self.client.post(reverse("manufacturer_advance_create", args=[order.pk]), payload, **XHR)
        self.assertEqual(response.status_code, 200, response.content.decode())
        return ManufacturerAdvance.objects.get(pk=response.json()["id"])

    def toggle(self, item, flag, value=True, expected=None, **extra):
        data = {"flag": flag, "value": "1" if value else "0", **extra}
        if expected is not None:
            data["expected"] = expected
        return self.client.post(reverse("manufacturer_advance_toggle", args=[item.pk]), data, **XHR)


class ModelAndMigrationTests(TestCase):
    def test_migration_only_adds_new_tables(self):
        """只擴充：0230 只建新表、索引與限制，不改既有欄位，藍綠部署相容。"""
        from importlib import import_module

        migration = import_module("sales.migrations.0230_t334_manufacturer_advances").Migration
        self.assertIn(("sales", "0229_t332_plate_insurance_fee_expense"), migration.dependencies)
        kinds = {type(operation).__name__ for operation in migration.operations}
        self.assertLessEqual(kinds, {"CreateModel", "AddIndex", "AddConstraint"})

    def test_reserved_origin_fields_for_auto_attach(self):
        """第二版「依活動自動掛上」：origin 先只有手動，origin_key 非空時同一張單不能重複。"""
        self.assertEqual([value for value, _ in ManufacturerAdvance.Origin.choices], ["manual"])
        names = {constraint.name for constraint in ManufacturerAdvance._meta.constraints}
        self.assertIn("manufacturer_advance_unique_origin_key", names)


class FinanceIsolationTests(AdvanceTestBase):
    def test_items_do_not_change_profit_or_customer_receivable(self):
        order = self.make_order()
        OrderOperationsProfile.objects.filter(order=order).update(actual_disbursement=79800, vehicle_cost=60000, gift_expense=500)
        profile = OrderOperationsProfile.objects.get(order=order)
        before = (profile.net_profit, profile.total_expense, finance_totals(profile), payment_summary(order))
        order.refresh_from_db()
        balance_before = (order.calculated_balance, order.actual_balance)
        blockers_before = order.delivery_blockers()

        cash = self.add(order, amount="1500")
        gift = self.add(order, kind="gift", gift_name="虛構安全帽", gift_quantity="2", recipient="dealer")
        self.assertEqual(self.toggle(cash, "reimbursed").status_code, 200)
        self.assertEqual(self.toggle(gift, "handed_over").status_code, 200)
        self.client.post(reverse("manufacturer_advance_payout"), {"items": [gift.pk], "paid_on": "2026-11-20", "amount": "900"}, **XHR)

        profile = OrderOperationsProfile.objects.get(order=order)
        order.refresh_from_db()
        self.assertEqual((profile.net_profit, profile.total_expense, finance_totals(profile), payment_summary(order)), before)
        self.assertEqual((order.calculated_balance, order.actual_balance), balance_before)
        self.assertEqual(order.delivery_blockers(), blockers_before)

    def test_order_page_shows_block_below_finance_without_touching_totals(self):
        order = self.make_order()
        page = self.client.get(reverse("order_detail", args=[order.pk]) + "?tab=finance").content.decode()
        # 沒有項目：只有一列「＋ 新增」。
        self.assertIn('id="manufacturer-advances"', page)
        self.assertIn("advance-block is-empty", page)
        self.assertIn("＋ 新增", page)
        self.assertLess(page.index("data-finance-ledger"), page.index('id="manufacturer-advances"'))
        self.add(order, amount="2500")
        page = self.client.get(reverse("order_detail", args=[order.pk]) + "?tab=finance").content.decode()
        self.assertIn("虛構年終現金回饋", page)
        self.assertIn("不算進收支合計與淨利", page)


class CreateValidationTests(AdvanceTestBase):
    def test_defaults_and_suggestions(self):
        order = self.make_order()
        page = self.client.get(reverse("order_detail", args=[order.pk]) + "?tab=finance").content.decode()
        self.assertIn('name="manufacturer" type="text" maxlength="80" value="SUZUKI"', page)  # 預設訂單的品牌
        self.add(order, campaign_name="虛構春季加碼")
        other = self.make_order()
        page = self.client.get(reverse("order_detail", args=[other.pk]) + "?tab=finance").content.decode()
        self.assertIn('<option value="虛構春季加碼"></option>', page)  # 打過的字下次可以直接點選

    def test_cash_needs_amount_gift_needs_name_and_quantity(self):
        order = self.make_order()
        url = reverse("manufacturer_advance_create", args=[order.pk])
        base = {"manufacturer": "SUZUKI", "campaign_name": "虛構活動", "recipient": "customer"}
        response = self.client.post(url, {**base, "kind": "cash", "amount": ""}, **XHR)
        self.assertEqual(response.status_code, 400)
        self.assertIn("amount", response.json()["errors"])
        response = self.client.post(url, {**base, "kind": "gift", "gift_name": "", "gift_quantity": "0"}, **XHR)
        self.assertEqual(set(response.json()["errors"]), {"gift_name", "gift_quantity"})
        self.assertFalse(ManufacturerAdvance.objects.exists())

    def test_dealer_recipient_only_on_dealer_orders(self):
        store_order = self.make_order(source_type="store", source=None)
        response = self.client.post(reverse("manufacturer_advance_create", args=[store_order.pk]), {
            "manufacturer": "SUZUKI", "campaign_name": "虛構活動", "recipient": "dealer", "kind": "cash", "amount": "100"}, **XHR)
        self.assertEqual(response.status_code, 400)
        self.assertIn("recipient", response.json()["errors"])

    def test_void_and_restore_with_audit_events(self):
        order = self.make_order()
        item = self.add(order)
        response = self.client.post(reverse("manufacturer_advance_void", args=[item.pk]), {}, **XHR)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(f'data-advance-item="{item.pk}"', response.json()["html"])
        self.assertEqual(advances.order_items(order), [])
        self.client.post(reverse("manufacturer_advance_void", args=[item.pk]), {"restore": "1"}, **XHR)
        self.assertEqual(advances.order_items(order), [item])
        # 勾過的不能刪。
        self.toggle(item, "handed_over")
        self.assertEqual(self.client.post(reverse("manufacturer_advance_void", args=[item.pk]), {}, **XHR).status_code, 409)
        self.assertGreaterEqual(OrderEvent.objects.filter(order=order, event_type=advances.EVENT_TYPE).count(), 4)


class PayoutTests(AdvanceTestBase):
    def test_difference_is_actual_minus_selected_cash_and_only_displayed(self):
        order = self.make_order()
        first = self.add(order, amount="1000")
        second = self.add(order, amount="500")
        gift = self.add(order, kind="gift", gift_name="虛構雨衣", gift_quantity="3")
        response = self.client.post(reverse("manufacturer_advance_payout"), {
            "items": [first.pk, second.pk, gift.pk], "paid_on": "2026-11-20", "amount": "1200"}, **XHR)
        self.assertEqual(response.status_code, 200, response.content.decode())
        self.assertIn("差額 −$300", response.json()["message"])
        payout = ManufacturerAdvancePayout.objects.get()
        self.assertEqual((payout.manufacturer, payout.amount, payout.paid_on, payout.handled_by),
                         ("SUZUKI", Decimal("1200"), date(2026, 11, 20), "測試主管"))
        self.assertEqual(set(payout.items.all()), {first, second, gift})
        totals = advances.payout_totals(list(payout.items.all()), payout.amount)
        self.assertEqual((totals["selected"], totals["actual"], totals["difference"]), (Decimal("1500"), Decimal("1200"), Decimal("-300")))
        first.refresh_from_db()
        self.assertEqual((first.reimbursed_on, first.reimbursed_by), (date(2026, 11, 20), "測試主管"))
        # 多撥也只是顯示差額。
        third = self.add(order, amount="800")
        response = self.client.post(reverse("manufacturer_advance_payout"), {"items": [third.pk], "paid_on": "2026-11-21", "amount": "1000"}, **XHR)
        self.assertIn("差額 ＋$200", response.json()["message"])

    def test_rejects_mixed_manufacturers_and_already_paid(self):
        order = self.make_order()
        suzuki = self.add(order)
        sym = self.add(order, manufacturer="SYM")
        response = self.client.post(reverse("manufacturer_advance_payout"), {"items": [suzuki.pk, sym.pk], "paid_on": "2026-11-20", "amount": "1"}, **XHR)
        self.assertEqual(response.status_code, 400)
        self.assertIn("同一家原廠", response.json()["message"])
        self.toggle(suzuki, "reimbursed")
        response = self.client.post(reverse("manufacturer_advance_payout"), {"items": [suzuki.pk], "paid_on": "2026-11-20", "amount": "1"}, **XHR)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["items"][0]["reimbursed"], True)
        self.assertFalse(ManufacturerAdvancePayout.objects.exists())

    def test_undo_payout_clears_items(self):
        order = self.make_order()
        first, second = self.add(order), self.add(order, amount="300")
        payout_id = self.client.post(reverse("manufacturer_advance_payout"), {
            "items": [first.pk, second.pk], "paid_on": "2026-11-20", "amount": "1300"}, **XHR).json()["payout"]
        response = self.client.post(reverse("manufacturer_advance_payout_void", args=[payout_id]), {}, **XHR)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(not state["reimbursed"] for state in response.json()["items"]))
        self.assertIsNotNone(ManufacturerAdvancePayout.objects.get(pk=payout_id).voided_at)
        # 單筆取消「原廠已撥」時把它移出撥款紀錄；最後一筆移出，紀錄自動作廢。
        payout_id = self.client.post(reverse("manufacturer_advance_payout"), {"items": [first.pk], "paid_on": "2026-11-22", "amount": "1000"}, **XHR).json()["payout"]
        self.toggle(first, "reimbursed", value=False)
        first.refresh_from_db()
        self.assertIsNone(first.payout_id)
        self.assertIsNotNone(ManufacturerAdvancePayout.objects.get(pk=payout_id).voided_at)


class SyncTests(AdvanceTestBase):
    """訂單頁、追蹤頁、營運總表側邊明細是同一份資料：在哪裡勾，三處都一樣。"""

    def test_tick_on_order_page_shows_everywhere(self):
        order = self.make_order()
        item = self.add(order)
        list_url = reverse("manufacturer_advance_list")
        self.assertContains(self.client.get(list_url + "?tab=reimburse"), f'data-advance-item="{item.pk}"')
        self.assertEqual(self.toggle(item, "reimbursed", expected="0").status_code, 200)  # 訂單頁勾
        self.assertNotContains(self.client.get(list_url + "?tab=reimburse"), f'data-advance-item="{item.pk}"')
        self.assertNotContains(self.client.get(list_url + "?tab=reimburse&fragment=panel"), f'data-advance-item="{item.pk}"')
        handover = self.client.get(list_url + "?tab=handover").content.decode()
        row = handover[handover.index(f'data-advance-item="{item.pk}"'):]
        self.assertIn('data-advance-toggle="reimbursed"', row)
        self.assertRegex(row[:row.index("</tr>")], r'data-advance-toggle="reimbursed"[^>]* checked')
        card = self.client.get(list_url + "?fragment=card").content.decode()
        self.assertIn("都撥了", card)

    def test_tick_on_tracking_page_shows_on_order_page(self):
        order = self.make_order()
        item = self.add(order)
        self.assertEqual(self.toggle(item, "handed_over", expected="0").status_code, 200)  # 追蹤頁／側邊明細勾
        page = self.client.get(reverse("order_detail", args=[order.pk]) + "?tab=finance").content.decode()
        block = page[page.index('id="manufacturer-advances"'):]
        self.assertRegex(block, r'data-advance-toggle="handed_over"[^>]* checked')
        self.assertIn(timezone.localdate().strftime("%m/%d") + "　測試主管", block)

    def test_stale_screen_state_is_rejected_with_latest_state(self):
        order = self.make_order()
        item = self.add(order)
        self.toggle(item, "handed_over", expected="0")
        # 另一處畫面還以為沒勾，又勾一次：不重複寫，回傳最新狀態。
        response = self.toggle(item, "handed_over", expected="0")
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.json()["items"][0]["handed_over"])
        # 取消（復原）回到沒勾。
        response = self.toggle(item, "handed_over", value=False, expected="1", undo="1")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["items"][0]["handed_over"])
        self.assertTrue(OrderEvent.objects.filter(order=order, description__contains="復原「已交給對象」").exists())


class PermissionTests(AdvanceTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.viewer = User.objects.create_user("viewer", password="Test-Only-123")
        cls.editor = User.objects.create_user("editor", password="Test-Only-123")
        cls.outsider = User.objects.create_user("outsider", password="Test-Only-123")
        for user in (cls.viewer, cls.editor, cls.outsider):
            UserAccessState.objects.create(user=user, configured=True)
            for key in ("orders", "work", "dashboard"):
                ScreenAccessGrant.objects.create(user=user, screen_key=key, view=True, operate=True)
        ScreenAccessGrant.objects.create(user=cls.viewer, screen_key="order_finance", view=True, operate=False)
        ScreenAccessGrant.objects.create(user=cls.editor, screen_key="order_finance", view=True, operate=True)

    def test_view_only_sees_but_cannot_tick(self):
        order = self.make_order()
        item = self.add(order)
        self.client.force_login(self.viewer)
        page = self.client.get(reverse("manufacturer_advance_list") + "?tab=handover").content.decode()
        self.assertIn(f'data-advance-item="{item.pk}"', page)
        self.assertRegex(page, r'data-advance-toggle="handed_over"[^>]* disabled')
        self.assertNotIn("登記原廠撥款", self.client.get(reverse("manufacturer_advance_list")).content.decode())
        order_page = self.client.get(reverse("order_detail", args=[order.pk]) + "?tab=finance").content.decode()
        self.assertIn("虛構年終現金回饋", order_page)
        self.assertNotIn("data-advance-add", order_page)
        self.assertEqual(self.toggle(item, "handed_over").status_code, 403)
        self.assertEqual(self.client.post(reverse("manufacturer_advance_create", args=[order.pk]), {}, **XHR).status_code, 403)
        self.assertEqual(self.client.post(reverse("manufacturer_advance_payout"), {"items": [item.pk]}, **XHR).status_code, 403)
        item.refresh_from_db()
        self.assertFalse(item.handed_over)

    def test_finance_editor_can_tick(self):
        order = self.make_order()
        item = self.add(order)
        self.client.force_login(self.editor)
        self.assertEqual(self.toggle(item, "handed_over").status_code, 200)
        self.assertContains(self.client.get(reverse("manufacturer_advance_list")), "登記原廠撥款")

    def test_order_scope_own_hides_other_orders_items(self):
        from sales.models import OrderAccountProfile

        mine = self.make_order(submitted_by=self.editor)
        theirs = self.make_order()
        my_item, their_item = self.add(mine), self.add(theirs)
        OrderAccountProfile.objects.create(user=self.editor, order_scope="own")
        self.client.force_login(self.editor)
        page = self.client.get(reverse("manufacturer_advance_list")).content.decode()
        self.assertIn(f'data-advance-item="{my_item.pk}"', page)
        self.assertNotIn(f'data-advance-item="{their_item.pk}"', page)
        self.assertEqual(self.toggle(their_item, "handed_over").status_code, 404)
        self.assertEqual(self.client.post(reverse("manufacturer_advance_payout"), {
            "items": [their_item.pk], "paid_on": "2026-11-20", "amount": "1"}, **XHR).status_code, 400)
        self.assertEqual(advances.summary(self.editor)["reimburse"]["count"], 1)

    def test_without_finance_permission_nothing_is_visible(self):
        order = self.make_order()
        self.add(order)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(reverse("manufacturer_advance_list")).status_code, 403)
        order_page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        self.assertNotIn('id="manufacturer-advances"', order_page)


class WaitingDaysTests(AdvanceTestBase):
    def age(self, item, days):
        ManufacturerAdvance.objects.filter(pk=item.pk).update(created_at=timezone.now() - timedelta(days=days))
        item.refresh_from_db()
        return item

    def test_reimburse_counts_from_registration_date_else_created(self):
        today = timezone.localdate()
        registered = self.make_order(registration_date=today - timedelta(days=9))
        pending = self.make_order()
        on_registered = self.age(self.add(registered), 2)
        on_pending = self.age(self.add(pending), 5)
        self.assertEqual(advances.waiting_days(on_registered, "reimburse", today), 9)  # 從實際領牌日
        self.assertEqual(advances.waiting_days(on_pending, "reimburse", today), 5)  # 還沒領牌：從建立日
        self.assertEqual(advances.waiting_days(on_registered, "handover", today), 2)  # 等交給對象：從建立日

    def test_alert_only_after_seven_days(self):
        today = timezone.localdate()
        order = self.make_order()
        item = self.age(self.add(order), 7)
        summary = advances.summary(self.admin, today)
        self.assertEqual((summary["reimburse"]["oldest"], summary["reimburse"]["alert"]), (7, False))
        self.age(item, 8)
        summary = advances.summary(self.admin, today)
        self.assertEqual((summary["reimburse"]["oldest"], summary["reimburse"]["alert"]), (8, True))
        self.assertEqual((summary["handover"]["oldest"], summary["handover"]["alert"]), (8, True))
        card = self.client.get(reverse("manufacturer_advance_list") + "?fragment=card").content.decode()
        self.assertEqual(card.count("最久 8 天"), 4)  # 兩半各一次，加上兩半的朗讀文字


class OperationsCardTests(AdvanceTestBase):
    def test_card_shows_current_open_items_regardless_of_period(self):
        old_order = self.make_order(order_date=date(2024, 1, 5), registration_date=date(2024, 1, 20))
        self.add(old_order, amount="1200")
        sym_order = self.make_order(vehicle_model=self.other_model, color=self.other_color)
        self.add(sym_order, manufacturer="SYM", amount="800")
        self.add(sym_order, manufacturer="SYM", kind="gift", gift_name="虛構手套", gift_quantity="4")
        summaries = []
        for period in ("month", "last_month", "ytd"):
            response = self.client.get(reverse("operations_report") + f"?period={period}")
            self.assertContains(response, "目前未結・不跟期間切換")
            summaries.append(response.context["advance_summary"])
        self.assertTrue(all(summary == summaries[0] for summary in summaries))
        summary = summaries[0]
        self.assertEqual([(row["manufacturer"], row["count"], row["amount"]) for row in summary["reimburse"]["rows"]],
                         [("SUZUKI", 1, Decimal("1200")), ("SYM", 2, Decimal("800"))])
        self.assertEqual((summary["handover"]["cash_count"], summary["handover"]["cash_amount"], summary["handover"]["gift_quantity"]),
                         (2, Decimal("2000"), 4))
        # 從實際領牌日（兩年前）算，超過 7 天。
        self.assertTrue(summary["reimburse"]["alert"])

    def test_card_hidden_without_finance_view(self):
        user = get_user_model().objects.create_user("ops-only", password="Test-Only-123")
        UserAccessState.objects.create(user=user, configured=True)
        ScreenAccessGrant.objects.create(user=user, screen_key="dashboard", view=True)
        ScreenAccessGrant.objects.create(user=user, screen_key="operations", view=True)
        self.client.force_login(user)
        response = self.client.get(reverse("operations_report"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "data-advance-ops-card")
