"""T-337：原廠代墊／代轉第二版——活動設定、依實際領牌日自動掛單、預計適用、單張訂單「不適用」。

- 活動設定比照原廠獎勵活動（欄位精簡：名稱、原廠、期間、適用車型（選填）、對象、內容）。
- 確認實際領牌後依實際領牌日自動掛上；還沒領牌依訂單日期顯示「預計適用」（不建項目）。
- 標「不適用」從該單移除，之後不再自動掛回去；可以復原。
- 不影響淨利、應收、傭金、交車；訂單頁、追蹤頁、營運總表卡片三處看到的是同一份資料。
測試資料一律明顯虛構。
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import (ManufacturerAdvance, ManufacturerAdvanceCampaign, ManufacturerAdvanceExclusion, OrderEvent,
                          OrderOperationsProfile, VehicleBrand, VehicleColor, VehicleModel)
from sales.services import manufacturer_advance as advances
from sales.services import manufacturer_advance_campaign as campaigns
from sales.services.finance_ledger import finance_totals
from sales.services.payment_summary import payment_summary
from sales.tests.test_manufacturer_advance_t334 import XHR, AdvanceTestBase


class CampaignTestBase(AdvanceTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for name in ("SUZUKI", "SYM"):
            VehicleBrand.objects.get_or_create(name=name)
        cls.sibling_model = VehicleModel.objects.create(brand="SUZUKI", name="虛構車型乙", energy_type="gas")
        cls.sibling_color = VehicleColor.objects.create(vehicle_model=cls.sibling_model, name="灰")

    def campaign_payload(self, **data):
        payload = {"name": "虛構領牌加碼回饋", "manufacturer": "SUZUKI", "effective_from": "2026-10-01",
                   "effective_to": "2026-10-31", "recipient": "customer", "kind": "cash", "amount": "1200",
                   "gift_quantity": "0", "active": "on"}
        payload.update(data)
        return payload

    def create_campaign(self, **data):
        response = self.client.post(reverse("manufacturer_advance_campaign_create"), self.campaign_payload(**data))
        self.assertEqual(response.status_code, 302, response.content.decode()[-1500:])
        self.client.get(response.url)  # 把存檔訊息讀掉，之後的頁面斷言才不會看到訊息裡的活動名稱
        return ManufacturerAdvanceCampaign.objects.latest("pk")

    def edit_campaign(self, campaign, **data):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("manufacturer_advance_campaign_edit", args=[campaign.pk]),
                                        self.campaign_payload(**data))
        self.assertEqual(response.status_code, 302, response.content.decode()[-1500:])
        self.client.get(response.url)
        campaign.refresh_from_db()
        return response

    def register(self, order, day):
        """確認實際領牌（直接寫欄位，跟 complete_registration 一樣帶 update_fields）。"""
        with self.captureOnCommitCallbacks(execute=True):
            order.registration_date = day
            order.registration_completed_at = timezone.now()
            order.save(update_fields=["registration_date", "registration_completed_at", "updated_at"])
        return order

    def auto_items(self, order, **filters):
        return list(ManufacturerAdvance.objects.filter(order=order, campaign__isnull=False, **filters))

    def exclude(self, order, campaign, restore=False):
        url = reverse("manufacturer_advance_exclude", args=[order.pk, campaign.pk])
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(url, {"restore": "1"} if restore else {}, **XHR)

    def order_page(self, order):
        return self.client.get(reverse("order_detail", args=[order.pk]) + "?tab=finance").content.decode()


class MigrationTests(CampaignTestBase):
    def test_migration_0231_only_expands(self):
        """先擴充後收斂：0231 只建表、加可空欄位與限制；origin 只多一個選項（資料庫 no-op），不刪不改欄位。"""
        from importlib import import_module

        migration = import_module("sales.migrations.0231_t337_manufacturer_advance_campaigns").Migration
        self.assertIn(("sales", "0230_t334_manufacturer_advances"), migration.dependencies)
        kinds = {type(operation).__name__ for operation in migration.operations}
        self.assertLessEqual(kinds, {"CreateModel", "AddField", "AddConstraint", "AddIndex", "AlterField"})
        altered = [operation for operation in migration.operations if type(operation).__name__ == "AlterField"]
        self.assertEqual([(operation.model_name, operation.name) for operation in altered], [("manufactureradvance", "origin")])
        added = [operation for operation in migration.operations if type(operation).__name__ == "AddField"]
        self.assertTrue(all(operation.field.null for operation in added))


class CampaignSettingsPageTests(CampaignTestBase):
    def test_list_and_form_have_the_six_fields_and_apply_button(self):
        page = self.client.get(reverse("manufacturer_advance_campaign_list")).content.decode()
        self.assertIn("代墊／代轉活動", page)
        self.assertIn('<button class="button primary" type="submit">套用</button>', page)
        self.assertNotIn("data-campaign-filters", page)  # 不用原廠獎勵清單的自動查詢
        form = self.client.get(reverse("manufacturer_advance_campaign_create")).content.decode()
        for name in ("name", "manufacturer", "effective_from", "effective_to", "vehicle_models", "recipient", "kind",
                     "amount", "gift_name", "gift_quantity"):
            self.assertIn(f'name="{name}"', form)
        self.assertRegex(form, r"適用車型<em>選填</em>")
        tracking = self.client.get(reverse("manufacturer_advance_list")).content.decode()
        self.assertIn(reverse("manufacturer_advance_campaign_list"), tracking)

    def test_validation(self):
        response = self.client.post(reverse("manufacturer_advance_campaign_create"), self.campaign_payload(
            amount="", effective_to="2026-09-01", vehicle_models=[self.other_model.pk]))
        self.assertEqual(response.status_code, 200)
        page = response.content.decode()
        self.assertIn("請填金額", page)
        self.assertIn("結束日不能早於開始日", page)
        self.assertIn("適用車型要是同一個原廠的車", page)
        response = self.client.post(reverse("manufacturer_advance_campaign_create"),
                                    self.campaign_payload(kind="gift", amount="", gift_name="", gift_quantity="0"))
        self.assertContains(response, "請填贈品名稱")
        self.assertFalse(ManufacturerAdvanceCampaign.objects.exists())

    def test_list_filters_and_tabs(self):
        self.create_campaign(name="虛構甲活動")
        self.create_campaign(name="虛構乙活動", manufacturer="SYM", active="")
        page = self.client.get(reverse("manufacturer_advance_campaign_list")).content.decode()
        self.assertIn("虛構甲活動", page)
        self.assertNotIn("虛構乙活動", page)
        page = self.client.get(reverse("manufacturer_advance_campaign_list") + "?tab=inactive&manufacturer=SYM").content.decode()
        self.assertIn("虛構乙活動", page)

    def test_delete_only_when_never_attached(self):
        order = self.register(self.make_order(), date(2026, 10, 5))
        used = self.create_campaign()
        self.assertEqual(len(self.auto_items(order)), 1)
        self.client.post(reverse("manufacturer_advance_campaign_delete", args=[used.pk]))
        self.assertTrue(ManufacturerAdvanceCampaign.objects.filter(pk=used.pk).exists())
        unused = self.create_campaign(name="虛構沒用到的活動", effective_from="2025-01-01", effective_to="2025-01-31")
        self.client.post(reverse("manufacturer_advance_campaign_delete", args=[unused.pk]))
        self.assertFalse(ManufacturerAdvanceCampaign.objects.filter(pk=unused.pk).exists())


class AutoAttachTests(CampaignTestBase):
    def test_campaign_save_attaches_by_actual_registration_date(self):
        inside = self.register(self.make_order(order_date=date(2026, 9, 1)), date(2026, 10, 5))
        outside = self.register(self.make_order(order_date=date(2026, 10, 3)), date(2026, 11, 2))
        other_brand = self.register(self.make_order(vehicle_model=self.other_model, color=self.other_color), date(2026, 10, 5))
        unregistered = self.make_order(order_date=date(2026, 10, 3))
        self.create_campaign()
        items = self.auto_items(inside)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual((item.origin, item.origin_key, item.campaign_name, item.amount, item.recipient),
                         ("campaign", f"campaign:{item.campaign_id}", "虛構領牌加碼回饋", Decimal("1200"), "customer"))
        # 訂單日期在期間內、實際領牌日不在：不掛（依實際領牌日）。
        self.assertEqual(self.auto_items(outside), [])
        self.assertEqual(self.auto_items(other_brand), [])
        self.assertEqual(self.auto_items(unregistered), [])
        self.assertTrue(OrderEvent.objects.filter(order=inside, description__contains="依活動自動掛上").exists())

    def test_registration_after_campaign_attaches_once(self):
        campaign = self.create_campaign()
        order = self.make_order()
        self.assertEqual(self.auto_items(order), [])
        self.register(order, date(2026, 10, 10))
        self.assertEqual(len(self.auto_items(order)), 1)
        # 再存一次（冪等）：一張單一個活動只有一筆。
        with self.captureOnCommitCallbacks(execute=True):
            order.save()
        self.edit_campaign(campaign)
        self.assertEqual(ManufacturerAdvance.objects.filter(order=order).count(), 1)

    def test_model_filter_and_dealer_recipient(self):
        listed = self.register(self.make_order(), date(2026, 10, 5))
        sibling = self.register(self.make_order(vehicle_model=self.sibling_model, color=self.sibling_color), date(2026, 10, 5))
        store = self.register(self.make_order(source_type="store", source=None), date(2026, 10, 5))
        self.create_campaign(vehicle_models=[self.model.pk])
        self.assertEqual(len(self.auto_items(listed)), 1)
        self.assertEqual(self.auto_items(sibling), [])
        self.create_campaign(name="虛構車行回饋", recipient="dealer", amount="800")
        self.assertEqual({item.campaign_name for item in self.auto_items(listed)}, {"虛構領牌加碼回饋", "虛構車行回饋"})
        # 對象是車行：門市單沒有車行，不掛。
        self.assertEqual({item.campaign_name for item in self.auto_items(store)}, {"虛構領牌加碼回饋"})

    def test_edit_updates_untouched_items_and_keeps_ticked_ones(self):
        untouched = self.register(self.make_order(), date(2026, 10, 5))
        ticked = self.register(self.make_order(), date(2026, 10, 6))
        campaign = self.create_campaign()
        ticked_item = self.auto_items(ticked)[0]
        self.assertEqual(self.toggle(ticked_item, "handed_over").status_code, 200)
        self.edit_campaign(campaign, amount="1500")
        self.assertEqual(self.auto_items(untouched)[0].amount, Decimal("1500"))
        self.assertEqual(self.auto_items(ticked)[0].amount, Decimal("1200"))
        # 期間改到不涵蓋：沒勾過的由系統移除，勾過的留著。
        self.edit_campaign(campaign, effective_from="2026-12-01", effective_to="2026-12-31")
        self.assertEqual(self.auto_items(untouched, voided_at__isnull=True), [])
        self.assertEqual(self.auto_items(untouched)[0].voided_by, campaigns.SYSTEM_VOID)
        self.assertEqual(len(self.auto_items(ticked, voided_at__isnull=True)), 1)
        # 改回來：重新掛上同一筆（不重複建）。
        self.edit_campaign(campaign)
        self.assertEqual(len(self.auto_items(untouched, voided_at__isnull=True)), 1)
        self.assertEqual(ManufacturerAdvance.objects.filter(order=untouched).count(), 1)

    def test_stopping_campaign_removes_untouched(self):
        order = self.register(self.make_order(), date(2026, 10, 5))
        campaign = self.create_campaign()
        self.edit_campaign(campaign, active="")
        self.assertEqual(self.auto_items(order, voided_at__isnull=True), [])

    def test_cancelled_and_deleted_orders_are_not_attached(self):
        cancelled = self.register(self.make_order(), date(2026, 10, 5))
        type(cancelled).all_objects.filter(pk=cancelled.pk).update(status="cancelled")
        self.create_campaign()
        self.assertEqual(self.auto_items(cancelled), [])

    def test_auto_item_shows_in_all_three_places(self):
        order = self.register(self.make_order(), date(2026, 10, 5))
        self.create_campaign()
        item = self.auto_items(order)[0]
        page = self.order_page(order)
        self.assertIn(f'data-advance-item="{item.pk}"', page)
        self.assertIn("依活動自動掛上", page)
        self.assertIn(reverse("manufacturer_advance_exclude", args=[order.pk, item.campaign_id]), page)
        tracking = self.client.get(reverse("manufacturer_advance_list")).content.decode()
        self.assertIn(f'data-advance-item="{item.pk}"', tracking)
        summary = advances.summary(self.admin)
        self.assertEqual((summary["reimburse"]["count"], summary["reimburse"]["amount"]), (1, Decimal("1200")))
        card = self.client.get(reverse("manufacturer_advance_list") + "?fragment=card").content.decode()
        self.assertIn("1,200", card)


class ProjectedTests(CampaignTestBase):
    def test_unregistered_order_shows_projected_by_order_date(self):
        order = self.make_order(order_date=date(2026, 10, 3))
        campaign = self.create_campaign()
        self.assertEqual([c.pk for c in campaigns.projected_campaigns(order)], [campaign.pk])
        page = self.order_page(order)
        self.assertIn("預計適用", page)
        self.assertIn("依訂單日期 2026/10/03 預計適用", page)
        # 預計適用只顯示：不建項目、不進追蹤頁與營運總表。
        self.assertEqual(self.auto_items(order), [])
        self.assertTrue(advances.summary(self.admin)["empty"])
        # 訂單日期不在期間內：不顯示。
        early = self.make_order(order_date=date(2026, 9, 1))
        self.assertEqual(campaigns.projected_campaigns(early), [])
        # 確認領牌後依實際領牌日掛上，預計適用消失。
        self.register(order, date(2026, 10, 20))
        self.assertEqual(campaigns.projected_campaigns(order), [])
        self.assertEqual(len(self.auto_items(order)), 1)


class NotApplicableTests(CampaignTestBase):
    def test_mark_removes_and_never_reattaches_until_restored(self):
        order = self.register(self.make_order(), date(2026, 10, 5))
        campaign = self.create_campaign()
        item = self.auto_items(order)[0]
        response = self.exclude(order, campaign)
        self.assertEqual(response.status_code, 200, response.content.decode())
        self.assertIn("不適用：", response.json()["html"])
        item.refresh_from_db()
        self.assertIsNotNone(item.voided_at)
        self.assertTrue(ManufacturerAdvanceExclusion.objects.filter(order=order, campaign=campaign).exists())
        # 之後不會再自動掛回去：改活動、訂單再存都一樣。
        self.edit_campaign(campaign, amount="1300")
        with self.captureOnCommitCallbacks(execute=True):
            order.save()
        self.assertEqual(self.auto_items(order, voided_at__isnull=True), [])
        self.assertNotIn(f'data-advance-item="{item.pk}"', self.client.get(reverse("manufacturer_advance_list")).content.decode())
        # 復原：依條件重新掛上同一筆，內容跟著活動。
        response = self.exclude(order, campaign, restore=True)
        self.assertEqual(response.status_code, 200)
        restored = self.auto_items(order, voided_at__isnull=True)
        self.assertEqual([(row.pk, row.amount) for row in restored], [(item.pk, Decimal("1300"))])
        self.assertTrue(OrderEvent.objects.filter(order=order, description__contains="標為不適用").exists())

    def test_old_delete_button_on_auto_item_also_marks_not_applicable(self):
        order = self.register(self.make_order(), date(2026, 10, 5))
        campaign = self.create_campaign()
        item = self.auto_items(order)[0]
        response = self.client.post(reverse("manufacturer_advance_void", args=[item.pk]), **XHR)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ManufacturerAdvanceExclusion.objects.filter(order=order, campaign=campaign).exists())

    def test_projected_can_be_marked_not_applicable(self):
        order = self.make_order(order_date=date(2026, 10, 3))
        campaign = self.create_campaign()
        self.assertEqual(self.exclude(order, campaign).status_code, 200)
        self.assertEqual(campaigns.projected_campaigns(order), [])
        self.register(order, date(2026, 10, 20))
        self.assertEqual(self.auto_items(order), [])

    def test_ticked_item_cannot_be_marked_not_applicable(self):
        order = self.register(self.make_order(), date(2026, 10, 5))
        campaign = self.create_campaign()
        item = self.auto_items(order)[0]
        self.toggle(item, "reimbursed")
        response = self.exclude(order, campaign)
        self.assertEqual(response.status_code, 409)
        item.refresh_from_db()
        self.assertIsNone(item.voided_at)
        self.assertFalse(ManufacturerAdvanceExclusion.objects.exists())


class FinanceIsolationTests(CampaignTestBase):
    def snapshot(self, order):
        order.refresh_from_db()
        profile = OrderOperationsProfile.objects.get(order=order)
        return {
            "net_profit": profile.net_profit, "total_expense": profile.total_expense, "totals": finance_totals(profile),
            "payment": payment_summary(order), "balance": (order.calculated_balance, order.actual_balance),
            "customer_due": order.customer_balance_due,
            "commission": (profile.dealer_commission_expense, profile.dealer_commission_base,
                           profile.dealer_commission_adjustment, profile.dealer_commission_policy_id),
            "delivery": order.delivery_blockers(), "status": order.status,
        }

    def test_auto_attach_not_applicable_and_payout_change_no_money(self):
        """自動掛單、預計適用、不適用、登記撥款：淨利、應收、傭金、交車都不變。"""
        order = self.register(self.make_order(), date(2026, 10, 5))
        OrderOperationsProfile.objects.filter(order=order).update(
            actual_disbursement=79800, vehicle_cost=60000, dealer_commission_expense=2000, dealer_commission_base=2000)
        before = self.snapshot(order)
        campaign = self.create_campaign()
        gift = self.create_campaign(name="虛構贈品活動", kind="gift", amount="", gift_name="虛構安全帽", gift_quantity="1",
                                    recipient="dealer")
        self.assertEqual(self.snapshot(order), before)
        item = next(row for row in self.auto_items(order) if row.campaign_id == campaign.pk)
        self.toggle(item, "handed_over")
        self.client.post(reverse("manufacturer_advance_payout"), {"items": [item.pk], "paid_on": "2026-11-20", "amount": "1000"}, **XHR)
        self.exclude(order, gift)
        self.exclude(order, gift, restore=True)
        after = self.snapshot(order)
        self.assertEqual(after["commission"], before["commission"])  # 傭金不變
        self.assertEqual(after, before)

    def test_projected_does_not_change_money(self):
        order = self.make_order(order_date=date(2026, 10, 3))
        before = self.snapshot(order)
        campaign = self.create_campaign()
        self.order_page(order)
        self.exclude(order, campaign)
        self.assertEqual(self.snapshot(order), before)


class PayoutRemovalTests(CampaignTestBase):
    def test_panel_has_hooks_to_drop_paid_rows(self):
        """登記撥款後已撥的列要立即從待撥清單消失（T-337 順便修）：面板帶筆數與空狀態的掛勾，JS 靠它們移走列。"""
        order = self.make_order()
        self.add(order)
        page = self.client.get(reverse("manufacturer_advance_list")).content.decode()
        self.assertIn("data-advance-summary-count", page)
        self.assertIn("data-advance-empty hidden", page)
        with open("static/js/manufacturer-advance.js", encoding="utf-8") as handle:
            script = handle.read()
        self.assertIn("setPaidRowsHidden(paidIds, true)", script)
        self.assertIn("setPaidRowsHidden(paidIds, false)", script)


class PermissionTests(CampaignTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.viewer = User.objects.create_user("campaign-viewer", password="Test-Only-123")
        cls.finance = User.objects.create_user("campaign-finance", password="Test-Only-123")
        for user in (cls.viewer, cls.finance):
            UserAccessState.objects.create(user=user, configured=True)
            for key in ("orders", "work", "dashboard"):
                ScreenAccessGrant.objects.create(user=user, screen_key=key, view=True, operate=True)
        ScreenAccessGrant.objects.create(user=cls.viewer, screen_key="incentives", view=True, operate=False)
        ScreenAccessGrant.objects.create(user=cls.viewer, screen_key="order_finance", view=True, operate=False)
        ScreenAccessGrant.objects.create(user=cls.finance, screen_key="order_finance", view=True, operate=True)

    def test_settings_follow_incentives_and_not_applicable_follows_order_finance(self):
        order = self.make_order(order_date=date(2026, 10, 3))
        campaign = self.create_campaign()
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("manufacturer_advance_campaign_list")).status_code, 200)
        self.assertEqual(self.client.post(reverse("manufacturer_advance_campaign_create"), self.campaign_payload()).status_code, 403)
        self.assertEqual(self.exclude(order, campaign).status_code, 403)
        self.assertNotIn(reverse("manufacturer_advance_exclude", args=[order.pk, campaign.pk]), self.order_page(order))
        self.client.force_login(self.finance)
        self.assertEqual(self.client.get(reverse("manufacturer_advance_campaign_list")).status_code, 403)
        self.assertEqual(self.exclude(order, campaign).status_code, 200)
