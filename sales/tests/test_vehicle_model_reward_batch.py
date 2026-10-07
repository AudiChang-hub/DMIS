"""批次套用附加獎勵：預覽不寫入、只為勾選年式建立方案並存成本快照、自動結束沒有結束日的原方案、
各種重疊略過、日期驗證、多品項、權限與預覽後資料變更。"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import (
    DealerRewardCatalogItem,
    DealerRewardCostVersion,
    DealerVehicleRewardItem,
    DealerVehicleRewardPlan,
    UserAccountAuditLog,
    VehicleModel,
)
from sales.services import vehicle_model_reward_batch as reward_batch

URL = reverse("vehicle_model_reward_batch")
RewardType = DealerVehicleRewardItem.RewardType


def make_model(name, brand="SUZUKI"):
    return VehicleModel.objects.create(
        brand=brand, name=name, model_number=name, model_year=2026,
        model_code=VehicleModel.ModelType.CBS_DISC, energy_type=VehicleModel.EnergyType.GAS, displacement_cc=125,
    )


class RewardBatchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = get_user_model().objects.create_superuser("admin", password="Test-Only-123")
        cls.today = timezone.localdate()
        cls.start = cls.today + timedelta(days=5)
        cls.a = make_model("獎勵甲")
        cls.b = make_model("獎勵乙")
        cls.c = make_model("獎勵丙")
        cls.voucher = DealerRewardCatalogItem.objects.create(reward_type=RewardType.VOUCHER, name="郵政禮券", unit="元")
        cls.oil = DealerRewardCatalogItem.objects.create(reward_type=RewardType.PHYSICAL, name="機油", unit="瓶")
        DealerRewardCostVersion.objects.create(catalog_item=cls.voucher, unit_cost=1, effective_from=cls.today - timedelta(days=60))
        # 機油成本在新方案生效前調價，快照必須取生效日的版本。
        DealerRewardCostVersion.objects.create(catalog_item=cls.oil, unit_cost=180, effective_from=cls.today - timedelta(days=60),
                                               effective_to=cls.start - timedelta(days=1))
        DealerRewardCostVersion.objects.create(catalog_item=cls.oil, unit_cost=200, effective_from=cls.start)

    def setUp(self):
        self.client.force_login(self.root)

    def old_plan(self, model, *, start=None, end=None, active=True, items=((None, 3000),)):
        plan = DealerVehicleRewardPlan.objects.create(
            vehicle_model=model, effective_from=start or self.today - timedelta(days=30), effective_to=end, active=active,
        )
        for catalog, quantity in items:
            catalog = catalog or self.voucher
            DealerVehicleRewardItem.objects.create(plan=plan, catalog_item=catalog, reward_type=catalog.reward_type,
                                                   name=catalog.name, unit=catalog.unit, quantity=quantity)
        return plan

    def post(self, action="preview", *, selected=None, items=None, start=None, end="", close_open=True, **extra):
        data = {"action": action, "editor": "1", "effective_from": (start or self.start).isoformat(),
                "effective_to": end.isoformat() if hasattr(end, "isoformat") else end,
                "row": [self.a.pk, self.b.pk, self.c.pk],
                "selected": [model.pk for model in (selected if selected is not None else [self.a, self.b])],
                "item_catalog": [], "item_quantity": [], "item_note": [], **extra}
        for catalog, quantity, note in (items if items is not None else [(self.voucher, "10,000", ""), (self.oil, "2", "全合成")]):
            data["item_catalog"].append(str(catalog.pk) if catalog else "")
            data["item_quantity"].append(quantity)
            data["item_note"].append(note)
        if close_open:
            data["close_open"] = "1"
        return self.client.post(URL, data)

    def commit(self, preview, **kwargs):
        return self.client.post(URL, {"action": "commit", "token": preview.context["token"]}, **kwargs)

    def rows(self, response):
        return {row["model"].pk: row for row in response.context["rows"]}

    # ---- 畫面 ----

    def test_page_lists_current_plan_summary_and_defaults(self):
        self.old_plan(self.a, end=self.today + timedelta(days=90), items=((self.voucher, 10000), (self.oil, 2)))
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["state"]["start"], self.today)
        self.assertTrue(response.context["state"]["close_open"], "預設勾選自動結束原方案")
        rows = self.rows(response)
        end = self.today + timedelta(days=90)
        self.assertEqual(rows[self.a.pk]["current_summary"], f"郵政禮券 10,000 元、機油 2 瓶（至 {end:%Y/%m/%d}）")
        self.assertEqual(rows[self.b.pk]["current_summary"], "無")
        self.assertContains(response, "郵政禮券（元）")
        self.assertContains(response, "原方案沒有結束日時，自動設為新方案前一天結束")

    def test_batch_tool_has_reward_tab(self):
        response = self.client.get(reverse("vehicle_model_batch"))
        tab = next(tab for tab in response.context["dataset_tabs"] if tab["key"] == "reward")
        self.assertTrue(tab["href"].startswith(URL))
        self.assertContains(response, "附加獎勵")

    # ---- 預覽與寫入 ----

    def test_preview_does_not_write(self):
        response = self.post()
        self.assertEqual(response.context["stage"], "preview")
        self.assertEqual(response.context["applied_count"], 2)
        self.assertEqual(response.context["per_unit"], 10000 + 2 * 200)
        self.assertEqual(DealerVehicleRewardPlan.objects.count(), 0)
        self.assertContains(response, "確認套用到 2 個年式")

    def test_commit_creates_plans_with_cost_snapshot_for_selected_models_only(self):
        preview = self.post(end=self.start + timedelta(days=60), plan_note="十月促銷")
        response = self.commit(preview, follow=True)
        self.assertContains(response, "已為 2 個年式建立")
        self.assertFalse(DealerVehicleRewardPlan.objects.filter(vehicle_model=self.c).exists())
        for model in (self.a, self.b):
            plan = DealerVehicleRewardPlan.objects.get(vehicle_model=model)
            self.assertEqual((plan.effective_from, plan.effective_to, plan.active, plan.note),
                             (self.start, self.start + timedelta(days=60), True, "十月促銷"))
            items = {item.name: item for item in plan.items.all()}
            self.assertEqual(set(items), {"郵政禮券", "機油"})
            oil = items["機油"]
            self.assertEqual((oil.quantity, oil.unit, oil.reward_type, oil.note), (2, "瓶", RewardType.PHYSICAL, "全合成"))
            self.assertEqual((oil.unit_cost_snapshot, oil.cost_effective_on_snapshot), (Decimal("200"), self.start),
                             "成本快照取新方案生效日的成本版本")
            self.assertEqual((items["郵政禮券"].quantity, items["郵政禮券"].unit_cost_snapshot), (10000, 1))
        log = UserAccountAuditLog.objects.get(metadata__tool="vehicle_model_reward_batch")
        self.assertEqual(log.metadata["effective_from"], self.start.isoformat())
        self.assertEqual(log.metadata["per_unit_cost"], 10400)
        self.assertEqual(len(log.metadata["results"]), 2)

    def test_auto_close_previous_open_ended_plan(self):
        old = self.old_plan(self.a)
        preview = self.post()
        row = self.rows(preview)[self.a.pk]
        self.assertEqual(row["status"], reward_batch.CLOSE)
        self.assertContains(preview, f"將結束原方案（設為 {self.start - timedelta(days=1):%Y/%m/%d} 結束）")
        self.assertEqual(preview.context["closing_count"], 1)
        self.commit(preview)
        old.refresh_from_db()
        self.assertEqual(old.effective_to, self.start - timedelta(days=1))
        self.assertEqual(old.items.get().quantity, 3000, "原方案的項目不變")
        self.assertTrue(DealerVehicleRewardPlan.objects.filter(vehicle_model=self.a, effective_from=self.start).exists())
        log = UserAccountAuditLog.objects.get(metadata__tool="vehicle_model_reward_batch")
        result = next(r for r in log.metadata["results"] if r["model_id"] == self.a.pk)
        self.assertEqual((result["closed_id"], result["closed_to"]), (old.pk, (self.start - timedelta(days=1)).isoformat()))

    def test_option_off_skips_model_with_open_ended_plan(self):
        old = self.old_plan(self.a)
        preview = self.post(close_open=False)
        row = self.rows(preview)[self.a.pk]
        self.assertEqual(row["status"], reward_batch.SKIP)
        self.assertIn("沒有結束日", row["reason"])
        self.assertEqual(preview.context["applied_count"], 1)
        self.commit(preview)
        old.refresh_from_db()
        self.assertIsNone(old.effective_to)
        self.assertFalse(DealerVehicleRewardPlan.objects.filter(vehicle_model=self.a, effective_from=self.start).exists())
        self.assertTrue(DealerVehicleRewardPlan.objects.filter(vehicle_model=self.b, effective_from=self.start).exists())

    def test_bounded_overlap_is_skipped_and_untouched(self):
        end = self.start + timedelta(days=10)
        old = self.old_plan(self.a, end=end)
        preview = self.post()
        row = self.rows(preview)[self.a.pk]
        self.assertEqual(row["status"], reward_batch.SKIP)
        self.assertIn("已設定結束日", row["reason"])
        self.commit(preview)
        old.refresh_from_db()
        self.assertEqual(old.effective_to, end)
        self.assertEqual(DealerVehicleRewardPlan.objects.filter(vehicle_model=self.a).count(), 1)

    def test_bounded_plan_ending_before_start_does_not_block(self):
        self.old_plan(self.a, end=self.start - timedelta(days=1))
        self.assertEqual(self.rows(self.post())[self.a.pk]["status"], reward_batch.CREATE)

    def test_future_scheduled_plan_overlap_skipped_unless_new_plan_ends_before(self):
        scheduled = self.old_plan(self.a, start=self.start + timedelta(days=20))
        row = self.rows(self.post())[self.a.pk]
        self.assertEqual(row["status"], reward_batch.SKIP)
        self.assertIn("已排定", row["reason"])
        row = self.rows(self.post(end=self.start + timedelta(days=19)))[self.a.pk]
        self.assertEqual(row["status"], reward_batch.CREATE, "新方案在排定方案前結束就不重疊")
        scheduled.refresh_from_db()
        self.assertIsNone(scheduled.effective_to)

    def test_same_day_plan_is_skipped_even_when_inactive(self):
        self.old_plan(self.a, start=self.start, active=False)
        row = self.rows(self.post())[self.a.pk]
        self.assertEqual(row["status"], reward_batch.SKIP)
        self.assertIn("已有開始的方案（已停用）", row["reason"])

    def test_all_skipped_has_no_commit_button(self):
        self.old_plan(self.a, end=self.start + timedelta(days=3))
        preview = self.post(selected=[self.a])
        self.assertEqual(preview.context["applied_count"], 0)
        self.assertNotContains(preview, "確認套用到")
        response = self.commit(preview, follow=True)
        self.assertContains(response, "沒有可套用的年式")
        self.assertEqual(DealerVehicleRewardPlan.objects.count(), 1)

    def test_back_restores_inputs(self):
        preview = self.post(end=self.start + timedelta(days=7), close_open=False, plan_note="備註")
        response = self.client.post(URL, {"action": "back", "token": preview.context["token"],
                                          "row": [self.a.pk, self.b.pk, self.c.pk]})
        state = response.context["state"]
        self.assertEqual((state["start"], state["end"], state["close_open"], state["note"]),
                         (self.start, self.start + timedelta(days=7), False, "備註"))
        self.assertEqual(state["selected"], {self.a.pk, self.b.pk})
        self.assertEqual([(item["catalog_id"], item["quantity_raw"]) for item in response.context["items"]],
                         [(str(self.voucher.pk), "10000"), (str(self.oil.pk), "2")])

    # ---- 驗證 ----

    def test_date_validation(self):
        response = self.post(start=self.today - timedelta(days=1))
        self.assertIn("生效日期不可早於今天", " ".join(response.context["errors"]))
        response = self.post(end=self.start - timedelta(days=1))
        self.assertIn("結束日不可早於生效日", " ".join(response.context["errors"]))
        response = self.post(start=self.today)
        self.assertEqual(response.context["stage"], "preview", "今天可以生效")
        self.assertEqual(DealerVehicleRewardPlan.objects.count(), 0)

    def test_item_validation(self):
        cases = (
            ([], "請至少填寫一項獎勵"),
            ([(self.voucher, "0", "")], "部分獎勵項目需要修正"),
            ([(self.voucher, "1.5", "")], "部分獎勵項目需要修正"),
            ([(self.voucher, "", "")], "部分獎勵項目需要修正"),
            ([(None, "2", "")], "部分獎勵項目需要修正"),
            ([(self.voucher, "1", ""), (self.voucher, "2", "")], "部分獎勵項目需要修正"),
        )
        for items, message in cases:
            with self.subTest(items=items):
                response = self.post(items=items)
                self.assertEqual(response.context["stage"], "edit")
                self.assertIn(message, " ".join(response.context["errors"]))
        response = self.post(items=[(self.voucher, "1", ""), (self.voucher, "2", "")])
        self.assertEqual(response.context["items"][1]["error"], "同一方案不可重複填寫相同獎勵")
        self.oil.active = False
        self.oil.save()
        response = self.post(items=[(self.oil, "1", "")])
        self.assertIn("已停用", response.context["items"][0]["error"])
        self.assertIn("請至少勾選一個年式", " ".join(self.post(selected=[]).context["errors"]))
        self.assertEqual(DealerVehicleRewardPlan.objects.count(), 0)

    def test_parse_quantity(self):
        self.assertEqual(reward_batch.parse_quantity("10,000"), 10000)
        self.assertIsNone(reward_batch.parse_quantity(" "))
        for bad in ("-1", "0", "1.5", "abc", "9999999999"):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                reward_batch.parse_quantity(bad)

    # ---- 預覽後資料變更 ----

    def test_stale_preview_refused_when_plan_added(self):
        preview = self.post()
        self.old_plan(self.a, end=self.start + timedelta(days=30))
        response = self.commit(preview, follow=True)
        self.assertContains(response, "預覽後資料已被變更")
        self.assertFalse(DealerVehicleRewardPlan.objects.filter(effective_from=self.start).exists())

    def test_stale_preview_refused_when_open_plan_closed_elsewhere(self):
        old = self.old_plan(self.a)
        preview = self.post()
        DealerVehicleRewardPlan.objects.filter(pk=old.pk).update(effective_to=self.start + timedelta(days=3))
        response = self.commit(preview, follow=True)
        self.assertContains(response, "預覽後資料已被變更")
        old.refresh_from_db()
        self.assertEqual(old.effective_to, self.start + timedelta(days=3))
        self.assertFalse(DealerVehicleRewardPlan.objects.filter(effective_from=self.start).exists())

    def test_stale_preview_refused_when_cost_changes(self):
        preview = self.post()
        DealerRewardCostVersion.objects.filter(catalog_item=self.oil, effective_from=self.start).update(unit_cost=250)
        response = self.commit(preview, follow=True)
        self.assertContains(response, "成本版本已變更")
        self.assertEqual(DealerVehicleRewardPlan.objects.count(), 0)

    def test_tampered_token_refused(self):
        response = self.client.post(URL, {"action": "commit", "token": "bad"}, follow=True)
        self.assertContains(response, "預覽已過期")
        self.assertEqual(DealerVehicleRewardPlan.objects.count(), 0)


class RewardBatchPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.model = make_model("權限獎勵車")
        cls.item = DealerRewardCatalogItem.objects.create(reward_type=RewardType.CASH_GIFT, name="紅包", unit="元")

    def make_user(self, name, grants):
        user = get_user_model().objects.create_user(name, password="Test-Only-123")
        UserAccessState.objects.create(user=user, configured=True)
        for key, operate in grants.items():
            ScreenAccessGrant.objects.create(user=user, screen_key=key, view=True, operate=operate)
        self.client.force_login(user)
        return user

    def preview_data(self):
        return {"action": "preview", "editor": "1", "effective_from": timezone.localdate().isoformat(),
                "row": [self.model.pk], "selected": [self.model.pk],
                "item_catalog": [self.item.pk], "item_quantity": ["600"], "item_note": [""]}

    def test_commission_operate_can_use_without_models_screen(self):
        self.make_user("commission-op", {"commissions": True})
        page = self.client.get(URL)
        self.assertEqual(page.status_code, 200)
        self.assertEqual([tab["key"] for tab in page.context["dataset_tabs"]], ["reward"])
        preview = self.client.post(URL, self.preview_data())
        self.assertEqual(preview.context["stage"], "preview")
        self.client.post(URL, {"action": "commit", "token": preview.context["token"]})
        self.assertTrue(DealerVehicleRewardPlan.objects.filter(vehicle_model=self.model).exists())

    def test_view_only_cannot_post(self):
        self.make_user("commission-view", {"commissions": False})
        page = self.client.get(URL)
        self.assertEqual(page.status_code, 200)
        self.assertFalse(page.context["can_operate"])
        self.assertContains(page, "你只有查看車行附加獎勵的權限")
        self.assertEqual(self.client.post(URL, self.preview_data()).status_code, 403)
        self.assertEqual(DealerVehicleRewardPlan.objects.count(), 0)

    def test_without_commission_screen_denied(self):
        self.make_user("models-only", {"models": True})
        self.assertEqual(self.client.get(URL).status_code, 403)
        batch = self.client.get(reverse("vehicle_model_batch"))
        self.assertNotIn("reward", [tab["key"] for tab in batch.context["dataset_tabs"]])
