"""T-261：補助步驟「已完成」＝所有補助項目都已申請；只看申請狀態，不看附件、不看撥款（使用者 2026-11-20）。"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import OrderOperationsProfile, SalesOrder, SubsidyItem, VehicleColor, VehicleModel
from sales.services.order_steps import build_order_steps


class SubsidyStepAppliedTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("admin", password="test-only")
        model = VehicleModel.objects.create(brand="示範牌", name="補助車", energy_type=VehicleModel.EnergyType.GAS)
        color = VehicleColor.objects.create(vehicle_model=model, name="白")
        # 汰舊單、補助基本資料齊全（舊車牌、同一車主、有補助項目）。
        self.order = SalesOrder.objects.create(
            owner_name="示範客戶", owner_phone="0900000000", owner_address="示範市", owner_id_number="A100000001",
            vehicle_model=model, color=color, id_verified=True, is_trade_in_subsidy=True, trade_in_plate="ABC-1234",
            old_owner_same_as_owner=True,
        )

    def add_item(self, name, status=SubsidyItem.Status.NOT_SUBMITTED, order=None):
        return SubsidyItem.objects.create(order=order or self.order, category=SubsidyItem.Category.LOCAL,
                                          item_name=name, expected_amount=5000, status=status)

    def step(self, order=None):
        order = SalesOrder.objects.get(pk=(order or self.order).pk)
        return build_order_steps(order)["steps"]["subsidy"]

    def test_all_items_applied_is_done(self):
        self.add_item("汰舊換新", SubsidyItem.Status.SUBMITTED)
        self.add_item("地方補助", SubsidyItem.Status.SUBMITTED)
        step = self.step()
        self.assertEqual((step["state"], step["state_label"], step["summary"]), ("done", "已完成", "2 項都已申請"))

    def test_partly_applied_is_pending_with_progress(self):
        self.add_item("汰舊換新", SubsidyItem.Status.SUBMITTED)
        self.add_item("地方補助")
        self.add_item("環保補助")
        step = self.step()
        self.assertEqual((step["state"], step["summary"]), ("todo", "1／3 項已申請"))
        self.assertNotEqual(step["state_label"], "已完成")
        # 訂單頁步驟清單也帶出摘要、不顯示已完成。
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[self.order.pk])).content.decode()
        self.assertIn("1／3 項已申請", page)

    def test_no_items_keeps_previous_display(self):
        # 汰舊單、基本資料齊、沒有補助項目（舊單用補助類型文字）：照舊「資料已齊」。
        SalesOrder.objects.filter(pk=self.order.pk).update(subsidy_type="汰舊換新")
        step = self.step()
        self.assertEqual((step["state"], step["summary"]), ("done", "資料已齊"))
        # 沒有啟用補助的訂單：照舊「隨時可填」，不變成待處理。
        SalesOrder.objects.filter(pk=self.order.pk).update(is_trade_in_subsidy=False)
        step = self.step()
        self.assertEqual((step["state"], step["summary"]), ("optional", "未申請（需要時可開啟）"))

    def test_disbursed_but_missing_documents_follows_application_only(self):
        # 已撥款、沒有任何附件：附件與撥款都不是條件，只看是否已申請。
        OrderOperationsProfile.objects.update_or_create(order=self.order, defaults={
            "subsidy_amount": 10000, "environment_ministry_status": OrderOperationsProfile.AgencyStatus.PAID,
            "local_government_status": OrderOperationsProfile.AgencyStatus.PAID,
        })
        self.assertFalse(self.order.subsidy_documents.exists())
        item = self.add_item("地方補助")
        step = self.step()
        self.assertEqual((step["state"], step["summary"]), ("todo", "0／1 項已申請"))
        SubsidyItem.objects.filter(pk=item.pk).update(status=SubsidyItem.Status.SUBMITTED)
        step = self.step()
        self.assertEqual((step["state"], step["summary"]), ("done", "1 項都已申請"))

    def test_trade_in_data_missing_stays_pending_even_if_all_applied(self):
        SalesOrder.objects.filter(pk=self.order.pk).update(trade_in_plate="")
        self.add_item("汰舊換新", SubsidyItem.Status.SUBMITTED)
        step = self.step()
        self.assertEqual((step["state"], step["summary"]), ("todo", "補助資料待補・1／1 項已申請"))

    def test_non_trade_in_items_also_count(self):
        # 非汰舊的補助（例如新購補助）也有項目時，同樣以已申請判斷。
        SalesOrder.objects.filter(pk=self.order.pk).update(is_trade_in_subsidy=False, trade_in_plate="")
        self.add_item("新購補助")
        self.assertEqual(self.step()["summary"], "0／1 項已申請")
        SubsidyItem.objects.filter(order=self.order).update(status=SubsidyItem.Status.SUBMITTED)
        self.assertEqual(self.step()["state"], "done")
