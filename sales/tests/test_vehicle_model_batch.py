"""批次調整：試算算法、預覽不寫入、只為勾選且有變更的列建立新版本，基礎傭金立即生效並留紀錄。"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import (
    UserAccountAuditLog,
    VehicleIncentiveRule,
    VehicleModel,
    VehiclePriceVersion,
    VehicleSettlementCostRule,
)
from sales.services import vehicle_model_batch as batch
from sales.services.vehicle_model_copy import first_of_next_month

BATCH_URL = reverse("vehicle_model_batch")


class AdjustmentMathTests(SimpleTestCase):
    def test_add_percent_and_set(self):
        self.assertEqual(batch.apply_adjustment(Decimal("68000"), "add", 1500), Decimal("69500"))
        self.assertEqual(batch.apply_adjustment(Decimal("68000"), "add", -500), Decimal("67500"))
        self.assertEqual(batch.apply_adjustment(Decimal("68000"), "percent", 3), Decimal("70040"))
        self.assertEqual(batch.apply_adjustment(Decimal("68000"), "percent", 3, 100), Decimal("70000"))
        self.assertEqual(batch.apply_adjustment(Decimal("99800"), "percent", 3, 100), Decimal("102800"))
        self.assertEqual(batch.apply_adjustment(Decimal("1000"), "percent", Decimal("-2.5")), Decimal("975"))
        self.assertEqual(batch.apply_adjustment(Decimal("1250"), "add", 0, 100), Decimal("1300"), "四捨五入，.5 進位")
        self.assertEqual(batch.apply_adjustment(Decimal("68000"), "set", 70000), Decimal("70000"))
        self.assertEqual(batch.apply_adjustment(None, "set", 500), Decimal("500"))

    def test_missing_current_and_negative_results(self):
        self.assertIsNone(batch.apply_adjustment(None, "add", 500))
        self.assertIsNone(batch.apply_adjustment(None, "percent", 5))
        with self.assertRaises(ValueError):
            batch.apply_adjustment(Decimal("300"), "add", -500)

    def test_parse_amount(self):
        self.assertEqual(batch.parse_amount("70,000"), Decimal("70000"))
        self.assertEqual(batch.parse_amount(" $1,500 元 "), Decimal("1500"))
        self.assertIsNone(batch.parse_amount(""))
        for bad in ("abc", "-1", "10.5", "NaN"):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                batch.parse_amount(bad)


class BatchAdjustTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = get_user_model().objects.create_superuser("admin", password="Test-Only-123")
        cls.today = timezone.localdate()
        cls.start = cls.today - timedelta(days=30)
        cls.day = first_of_next_month(cls.today)
        cls.a = cls.make_model("批次甲", commission=1000)
        cls.b = cls.make_model("批次乙", commission=1200)
        cls.c = cls.make_model("批次丙", commission=800)
        cls.prices = {
            model.pk: VehiclePriceVersion.objects.create(
                vehicle_model=model, cash_price=cash, suggested_price=cash + 4000,
                suggested_price_includes_registration=False, effective_from=cls.start,
            )
            for model, cash in ((cls.a, 68000), (cls.b, 71000), (cls.c, 52500))
        }
        VehicleSettlementCostRule.objects.create(vehicle_model=cls.a, amount=56000, effective_from=cls.start)
        VehicleIncentiveRule.objects.create(vehicle_model=cls.a, sales_bonus=1000, promotion_subsidy=2000,
                                            installment_interest_subsidy=500, effective_from=cls.start)

    @classmethod
    def make_model(cls, name, *, commission):
        return VehicleModel.objects.create(
            brand="SUZUKI", name=name, model_number=name, model_year=2026,
            model_code=VehicleModel.ModelType.CBS_DISC, energy_type=VehicleModel.EnergyType.GAS,
            displacement_cc=125, base_dealer_commission=commission,
        )

    def setUp(self):
        self.client.force_login(self.root)

    def post(self, action, dataset, values, *, selected=None, day=None, **extra):
        data = {"action": action, "dataset": dataset, "effective_from": (day or self.day).isoformat(),
                "row": [self.a.pk, self.b.pk, self.c.pk], **extra}
        for pk in (selected if selected is not None else {pk for pk, _field in values}):
            data[f"sel_{pk}"] = "1"
        for (pk, field), value in values.items():
            data[f"new_{field}_{pk}"] = value
        return self.client.post(BATCH_URL, data)

    def test_default_effective_date_is_today_and_future_date_is_flagged(self):
        from django.utils import timezone

        today = timezone.localdate()
        page = self.client.get(BATCH_URL, {"dataset": "price"})
        self.assertContains(page, f'value="{today.isoformat()}"')
        self.assertContains(page, "預設今天、立即生效")
        future = self.client.get(BATCH_URL, {"dataset": "price", "effective_from": self.day.isoformat()})
        self.assertContains(future, "起才生效，在此之前仍用目前價格")

    def test_page_lists_current_values(self):
        response = self.client.get(BATCH_URL, {"dataset": "price", "effective_from": self.day.isoformat()})
        rows = {row["model"].pk: row for row in response.context["rows"]}
        self.assertEqual(rows[self.a.pk]["cells"][0]["current"], 68000)
        self.assertEqual(rows[self.c.pk]["cells"][1]["current"], 56500)
        self.assertEqual(response.context["effective_from"], self.day)

    def test_preview_does_not_write(self):
        response = self.post("preview", "price", {(self.a.pk, "cash_price"): "69,500"})
        self.assertEqual(response.context["stage"], "preview")
        self.assertEqual(response.context["change_count"], 1)
        self.assertEqual(VehiclePriceVersion.objects.count(), 3)
        self.assertContains(response, "確認建立 1 筆新版本")

    def test_commit_creates_versions_for_selected_changed_rows_only(self):
        preview = self.post(
            "preview", "price",
            {
                (self.a.pk, "cash_price"): "69500",
                (self.b.pk, "cash_price"): "71000",   # 與目前相同：不算變更
                (self.c.pk, "cash_price"): "60000",   # 未勾選：不變
            },
            selected={self.a.pk, self.b.pk},
        )
        self.assertEqual([line["id"] for line in preview.context["lines"]], [self.a.pk])
        self.client.post(BATCH_URL, {"action": "commit", "token": preview.context["token"]})
        created = VehiclePriceVersion.objects.get(vehicle_model=self.a, effective_from=self.day)
        self.assertEqual((created.cash_price, created.suggested_price, created.suggested_price_includes_registration),
                         (69500, 72000, False), "未改的建議售價與含牌險設定沿用目前版本")
        self.assertFalse(VehiclePriceVersion.objects.filter(vehicle_model__in=[self.b, self.c], effective_from=self.day).exists())
        old = self.prices[self.a.pk]
        old.refresh_from_db()
        self.assertEqual((old.cash_price, old.effective_to), (68000, None))
        log = UserAccountAuditLog.objects.get(metadata__tool="vehicle_model_batch")
        self.assertEqual(log.metadata["results"][0]["fields"], {"cash_price": ["68000", "69500"]})

    def test_server_side_operations_match_math(self):
        cases = (
            ("add", "1500", "1", {self.a.pk: "69,500", self.b.pk: "72,500"}),
            ("percent", "3", "100", {self.a.pk: "70,000", self.b.pk: "73,100"}),
            ("set", "65000", "1", {self.a.pk: "65,000", self.b.pk: "65,000"}),
        )
        for op, value, step, expected in cases:
            with self.subTest(op=op):
                response = self.post("apply", "price", {}, selected={self.a.pk, self.b.pk},
                                     op=op, op_value=value, op_round=step, op_field="cash_price")
                rows = {row["model"].pk: row["cells"][0]["new"] for row in response.context["rows"]}
                self.assertEqual({pk: rows[pk] for pk in expected}, expected)
                self.assertEqual(rows[self.c.pk], "", "未勾選的列不套用")
        self.assertEqual(VehiclePriceVersion.objects.count(), 3)

    def test_cost_and_incentive_create_new_versions(self):
        preview = self.post("preview", "cost", {(self.a.pk, "amount"): "57000", (self.b.pk, "amount"): "50000"})
        self.client.post(BATCH_URL, {"action": "commit", "token": preview.context["token"]})
        self.assertEqual(VehicleSettlementCostRule.objects.get(vehicle_model=self.a, effective_from=self.day).amount, 57000)
        self.assertEqual(VehicleSettlementCostRule.objects.get(vehicle_model=self.b, effective_from=self.day).amount, 50000)
        preview = self.post("preview", "incentive", {(self.a.pk, "promotion_subsidy"): "2500"})
        self.client.post(BATCH_URL, {"action": "commit", "token": preview.context["token"]})
        rule = VehicleIncentiveRule.objects.get(vehicle_model=self.a, effective_from=self.day)
        self.assertEqual((rule.sales_bonus, rule.promotion_subsidy, rule.installment_interest_subsidy), (1000, 2500, 500))

    def test_base_commission_changes_immediately_and_is_audited(self):
        preview = self.post("preview", "commission", {(self.a.pk, "base_dealer_commission"): "1300"})
        self.assertTrue(preview.context["immediate"])
        self.assertContains(preview, "立即生效")
        self.client.post(BATCH_URL, {"action": "commit", "token": preview.context["token"]})
        self.a.refresh_from_db()
        self.b.refresh_from_db()
        self.assertEqual((self.a.base_dealer_commission, self.b.base_dealer_commission), (1300, 1200))
        log = UserAccountAuditLog.objects.get(metadata__tool="vehicle_model_batch")
        self.assertEqual(log.metadata["dataset"], "commission")
        self.assertEqual(log.metadata["results"][0]["fields"], {"base_dealer_commission": ["1000", "1300"]})
        self.assertIsNone(log.metadata["effective_from"])

    def test_stale_preview_is_rejected(self):
        preview = self.post("preview", "price", {(self.a.pk, "cash_price"): "69500"})
        VehiclePriceVersion.objects.filter(pk=self.prices[self.a.pk].pk).update(cash_price=68800)
        response = self.client.post(BATCH_URL, {"action": "commit", "token": preview.context["token"]}, follow=True)
        self.assertContains(response, "預覽後資料已被變更")
        self.assertFalse(VehiclePriceVersion.objects.filter(effective_from=self.day).exists())

    def test_existing_version_on_date_locks_row(self):
        VehiclePriceVersion.objects.create(vehicle_model=self.b, cash_price=72000, effective_from=self.day)
        response = self.post("preview", "price", {(self.b.pk, "cash_price"): "73000"})
        self.assertEqual(response.context["stage"], "edit")
        row = next(row for row in response.context["rows"] if row["model"].pk == self.b.pk)
        self.assertIn("已有版本", row["locked"])
        self.assertIn("沒有任何變更", " ".join(response.context["errors"]))

    def test_invalid_amount_and_past_date_rejected(self):
        response = self.post("preview", "price", {(self.a.pk, "cash_price"): "abc"})
        self.assertIn("部分金額格式不正確", " ".join(response.context["errors"]))
        yesterday = self.today - timedelta(days=1)
        response = self.post("preview", "price", {(self.a.pk, "cash_price"): "69000"}, day=yesterday)
        self.assertIn("生效日期不可早於今天", " ".join(response.context["errors"]))
        with self.assertRaises(ValidationError):
            batch.commit_changes(dataset="price", changes=[{"id": self.a.pk, "label": "x",
                                                            "fields": {"cash_price": ["68000", "69000"]}}],
                                 effective_from=yesterday, actor=self.root)
        self.assertEqual(VehiclePriceVersion.objects.count(), 3)

    def test_back_restores_inputs(self):
        preview = self.post("preview", "price", {(self.a.pk, "cash_price"): "69500"})
        response = self.client.post(BATCH_URL, {"action": "back", "token": preview.context["token"],
                                                "row": [self.a.pk, self.b.pk, self.c.pk]})
        row = next(row for row in response.context["rows"] if row["model"].pk == self.a.pk)
        self.assertTrue(row["selected"])
        self.assertEqual(row["cells"][0]["new"], "69,500")

    def test_list_page_links_to_tools(self):
        response = self.client.get(reverse("vehicle_model_list"))
        self.assertContains(response, BATCH_URL)
        self.assertContains(response, reverse("vehicle_model_copy"))


class BatchPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.model = VehicleModel.objects.create(
            brand="SYM", name="權限車", model_number="PM1", model_year=2026,
            energy_type=VehicleModel.EnergyType.GAS, displacement_cc=125,
        )
        VehicleSettlementCostRule.objects.create(vehicle_model=cls.model, amount=50000,
                                                 effective_from=timezone.localdate() - timedelta(days=10))

    def make_user(self, name, grants):
        user = get_user_model().objects.create_user(name, password="Test-Only-123")
        UserAccessState.objects.create(user=user, configured=True)
        for key, operate in grants.items():
            ScreenAccessGrant.objects.create(user=user, screen_key=key, view=True, operate=operate)
        self.client.force_login(user)
        return user

    def test_datasets_follow_screen_permissions(self):
        self.make_user("models-costs-view", {"models": True, "costs": False})
        response = self.client.get(BATCH_URL, {"dataset": "cost"})
        self.assertEqual([tab["key"] for tab in response.context["dataset_tabs"]], ["price", "cost"])
        self.assertFalse(response.context["can_operate"])
        day = first_of_next_month()
        response = self.client.post(BATCH_URL, {"action": "preview", "dataset": "cost", "effective_from": day.isoformat(),
                                                "row": [self.model.pk], f"sel_{self.model.pk}": "1",
                                                f"new_amount_{self.model.pk}": "51000"})
        self.assertIn("沒有這項資料的操作權限", " ".join(response.context["errors"]))
        self.assertEqual(VehicleSettlementCostRule.objects.count(), 1)

    def test_view_only_models_cannot_post(self):
        self.make_user("viewer", {"models": False})
        self.assertEqual(self.client.get(BATCH_URL).status_code, 200)
        self.assertEqual(self.client.post(BATCH_URL, {"action": "preview", "dataset": "price"}).status_code, 403)
        self.assertNotContains(self.client.get(reverse("vehicle_model_list")), BATCH_URL)

    def test_without_models_screen_denied(self):
        self.make_user("costs-only", {"costs": True})
        self.assertEqual(self.client.get(BATCH_URL).status_code, 403)
