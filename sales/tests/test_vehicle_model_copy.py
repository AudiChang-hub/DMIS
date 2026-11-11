"""機種沿用：沿用到新年式、沿用到新生效日與新增版本預填；只建立新版本，不改舊版本。"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import (
    DealerRewardCampaign,
    DealerRewardCampaignItem,
    DealerRewardCatalogItem,
    IncentiveCampaign,
    InstallmentCompany,
    InstallmentPlanOption,
    InstallmentPlanVersion,
    UserAccountAuditLog,
    VehicleCatalogEntry,
    VehicleColor,
    VehicleModel,
    VehiclePriceVersion,
    VehicleSettlementCostRule,
)
from sales.services import vehicle_model_copy as service

COPY_URL = reverse("vehicle_model_copy")


class VehicleModelCopyBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.root = user_model.objects.create_superuser("admin", password="Test-Only-123")
        cls.today = timezone.localdate()
        cls.start = cls.today - timedelta(days=40)
        cls.day = service.first_of_next_month(cls.today)
        cls.model = cls.make_model("沿用測試車", 2026, commission=1500)
        VehicleColor.objects.create(vehicle_model=cls.model, name="珍珠白", catalog_image="catalog/colors/2026/09/white.jpg")
        VehicleColor.objects.create(vehicle_model=cls.model, name="停產灰", active=False)
        VehicleCatalogEntry.objects.update_or_create(
            vehicle_model=cls.model,
            defaults={"image": "catalog/2026/09/main.jpg", "description": "通勤首選", "position": 7},
        )
        cls.price = VehiclePriceVersion.objects.create(
            vehicle_model=cls.model, cash_price=68000, suggested_price=72000,
            suggested_price_includes_registration=False, effective_from=cls.start,
        )
        cls.company = InstallmentCompany.objects.create(name="測試分期")
        cls.plan = InstallmentPlanVersion.objects.create(vehicle_model=cls.model, effective_from=cls.start)
        InstallmentPlanOption.objects.create(
            version=cls.plan, periods=12, monthly_amount=6000, company=cls.company,
            expected_disbursement_method="fixed", expected_disbursement_fixed_amount=60000,
            extra_disbursement_bonus=300,
        )
        InstallmentPlanOption.objects.create(
            version=cls.plan, periods=24, monthly_amount=3100, company=cls.company,
            expected_disbursement_rate=Decimal("92.50"),
        )
        cls.catalog_item = DealerRewardCatalogItem.objects.create(reward_type="cash_gift", name="紅包", unit="元")
        # 原廠獎勵與車行附加獎勵改為活動制（T-149）：沿用到新年式時把新年式加入指定原年式的活動。
        cls.reward = DealerRewardCampaign.objects.create(name="紅包活動", effective_from=cls.start)
        cls.reward.vehicle_models.set([cls.model])
        DealerRewardCampaignItem.objects.create(
            campaign=cls.reward, catalog_item=cls.catalog_item, reward_type="cash_gift", name="紅包", quantity=600, unit="元",
        )
        cls.cost = VehicleSettlementCostRule.objects.create(vehicle_model=cls.model, amount=56000, effective_from=cls.start)
        cls.incentive = IncentiveCampaign.objects.create(
            name="原廠常態", sales_bonus=1000, promotion_subsidy=2000,
            installment_interest_subsidy=500, effective_from=cls.start,
        )
        cls.incentive.vehicle_models.set([cls.model])
        cls.brand_campaign = IncentiveCampaign.objects.create(name="品牌活動", brands=["SUZUKI"], effective_from=cls.start)

    @classmethod
    def make_model(cls, name, year, *, commission=0, active=True):
        return VehicleModel.objects.create(
            brand="SUZUKI", name=name, model_number=f"{name[:2]}{year}", model_year=year,
            model_code=VehicleModel.ModelType.CBS_DISC, energy_type=VehicleModel.EnergyType.GAS,
            displacement_cc=125, base_dealer_commission=commission, active=active,
        )

    def setUp(self):
        self.client.force_login(self.root)

    def preview(self, mode, models, *, day=None, datasets=service.VERSIONED_KEYS, extras=service.YEAR_EXTRA_KEYS,
                activate=False, years=None):
        data = {
            "action": "preview", "mode": mode, "effective_from": (day or self.day).isoformat(),
            "datasets": list(datasets), "extras": list(extras),
            "row": [model.pk for model in models], "selected": [model.pk for model in models],
        }
        if activate:
            data["activate"] = "1"
        for model in models:
            data[f"year_{model.pk}"] = (years or {}).get(model.pk, (model.model_year or 0) + 1)
        return self.client.post(COPY_URL, data)

    def commit(self, response):
        return self.client.post(COPY_URL, {"action": "commit", "token": response.context["token"]})


class CopyToNewYearTests(VehicleModelCopyBase):
    def test_copies_everything_chosen_and_is_inactive_by_default(self):
        preview = self.preview("year", [self.model])
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.context["stage"], "preview")
        self.assertFalse(VehicleModel.objects.filter(model_year=2027).exists(), "預覽不可寫入")

        response = self.commit(preview)
        self.assertRedirects(response, f"{COPY_URL}?mode=year&result=1", fetch_redirect_response=False)
        new = VehicleModel.objects.get(name="沿用測試車", model_year=2027)
        self.assertFalse(new.active)
        self.assertEqual(new.family_id, self.model.family_id)
        self.assertEqual((new.model_code, new.displacement_cc, new.energy_type), (self.model.model_code, 125, "gas"))
        self.assertEqual(new.base_dealer_commission, 1500)
        self.assertEqual(set(new.factory_model_codes.values_list("pk", flat=True)),
                         set(self.model.factory_model_codes.values_list("pk", flat=True)))
        self.assertEqual(list(new.colors.values_list("name", "catalog_image")),
                         [("珍珠白", "catalog/colors/2026/09/white.jpg")])
        entry = VehicleCatalogEntry.objects.get(vehicle_model=new)
        self.assertEqual((entry.image.name, entry.description, entry.position, entry.published),
                         ("catalog/2026/09/main.jpg", "通勤首選", 7, False))

        price = new.price_versions.get()
        self.assertEqual((price.effective_from, price.cash_price, price.suggested_price,
                          price.suggested_price_includes_registration, price.effective_to),
                         (self.day, 68000, 72000, False, None))
        plan = new.installment_plan_versions.get()
        self.assertEqual(plan.effective_from, self.day)
        options = {option.periods: option for option in plan.options.all()}
        self.assertEqual(options[12].expected_disbursement_fixed_amount, 60000)
        self.assertEqual(options[12].extra_disbursement_bonus, 300)
        self.assertEqual(options[24].expected_disbursement_rate, Decimal("92.50"))
        self.assertEqual(new.settlement_cost_rules.get().amount, 56000)
        # 獎勵活動：新年式加入「指定年式」含原年式的活動；品牌條件的活動本來就涵蓋，不需加入。
        self.assertIn(new, self.incentive.vehicle_models.all())
        self.assertIn(new, self.reward.vehicle_models.all())
        self.assertFalse(self.brand_campaign.vehicle_models.exists())
        log = UserAccountAuditLog.objects.get(metadata__tool="vehicle_model_copy_year")
        self.assertEqual(log.actor, self.root)
        self.assertEqual(log.metadata["results"][0]["model_id"], new.pk)
        # 基準年式的版本完全不變。
        self.price.refresh_from_db()
        self.assertEqual((self.price.effective_to, self.price.cash_price), (None, 68000))

    def test_only_chosen_campaign_kind_adds_new_year(self):
        self.commit(self.preview("year", [self.model], datasets=["price"], extras=["reward_campaigns"]))
        new = VehicleModel.objects.get(model_year=2027)
        self.assertIn(new, self.reward.vehicle_models.all())
        self.assertNotIn(new, self.incentive.vehicle_models.all())
        self.assertEqual(self.reward.items.get().quantity, 600, "活動項目不變")
        self.assertEqual(new.base_dealer_commission, 0, "未勾選基礎傭金時新年式從 0 開始")
        self.assertFalse(new.colors.exists())

    def test_activate_publishes_catalog(self):
        self.commit(self.preview("year", [self.model], activate=True))
        new = VehicleModel.objects.get(model_year=2027)
        self.assertTrue(new.active)
        self.assertTrue(VehicleCatalogEntry.objects.get(vehicle_model=new).published)
        self.assertEqual(VehicleCatalogEntry.objects.get(vehicle_model=new).description, "通勤首選")

    def test_duplicate_year_is_blocked_with_clear_error(self):
        self.make_model("沿用測試車", 2027)
        preview = self.preview("year", [self.model])
        self.assertContains(preview, "已有 2027 年式")
        self.assertNotContains(preview, "確認建立")
        with self.assertRaises(ValidationError):
            service.execute_new_year(entries=[(self.model.pk, 2027)], effective_from=self.day,
                                     datasets=["price"], extras=[], activate=False, actor=self.root)
        response = self.commit(preview)
        self.assertEqual(VehicleModel.objects.filter(model_year=2027).count(), 1)
        self.assertFalse(UserAccountAuditLog.objects.filter(metadata__tool="vehicle_model_copy_year").exists())
        self.assertEqual(response.status_code, 302)

    def test_same_target_twice_in_one_batch_is_blocked(self):
        sibling = self.make_model("沿用測試車", 2025)
        preview = self.preview("year", [self.model, sibling], years={self.model.pk: 2027, sibling.pk: 2027})
        self.assertContains(preview, "本次已有另一列要建立相同的 2027 年式")
        self.assertTrue(preview.context["blocked"])

    def test_workspace_offers_copy_actions(self):
        response = self.client.get(reverse("vehicle_model_price_versions", args=[self.model.pk]))
        self.assertContains(response, f"{COPY_URL}?mode=year&amp;ids={self.model.pk}")
        self.assertContains(response, f"{COPY_URL}?mode=date&amp;ids={self.model.pk}")
        listing = self.client.get(COPY_URL, {"mode": "year", "ids": self.model.pk})
        self.assertEqual([row["model"].pk for row in listing.context["rows"]], [self.model.pk])
        self.assertTrue(listing.context["rows"][0]["selected"])
        self.assertEqual(listing.context["rows"][0]["target_year"], 2027)


class CopyToNewDateTests(VehicleModelCopyBase):
    def test_creates_versions_at_date_and_reports_missing_or_duplicate(self):
        other = self.make_model("另一台", 2026)
        VehiclePriceVersion.objects.create(vehicle_model=other, cash_price=50000, effective_from=self.start)
        VehiclePriceVersion.objects.create(vehicle_model=self.model, cash_price=69000, effective_from=self.day)
        preview = self.preview("date", [self.model, other], datasets=["price", "cost"])
        plan = {row["model"].pk: {item["dataset"]: item["status"] for item in row["items"]} for row in preview.context["plan"]}
        self.assertEqual(plan[self.model.pk], {"price": "duplicate", "cost": "create"})
        self.assertEqual(plan[other.pk], {"price": "create", "cost": "missing"})
        self.assertEqual(VehicleSettlementCostRule.objects.count(), 1, "預覽不可寫入")

        self.commit(preview)
        self.assertEqual(VehiclePriceVersion.objects.filter(vehicle_model=self.model).count(), 2)
        self.assertEqual(VehiclePriceVersion.objects.get(vehicle_model=other, effective_from=self.day).cash_price, 50000)
        cost = VehicleSettlementCostRule.objects.get(vehicle_model=self.model, effective_from=self.day)
        self.assertEqual((cost.amount, cost.effective_to, cost.active), (56000, None, True))
        self.assertFalse(VehicleSettlementCostRule.objects.filter(vehicle_model=other).exists())
        self.cost.refresh_from_db()
        self.assertEqual((self.cost.effective_from, self.cost.effective_to, self.cost.active), (self.start, None, True))
        log = UserAccountAuditLog.objects.get(metadata__tool="vehicle_model_copy_date")
        self.assertEqual(len(log.metadata["created"]), 2)
        self.assertEqual({item["status"] for item in log.metadata["skipped"]}, {"duplicate", "missing"})

    def test_rewards_are_campaigns_not_copied_by_date(self):
        """原廠獎勵與車行附加獎勵改為活動制（T-149），沿用到新生效日不再提供。"""
        self.assertEqual(service.VERSIONED_KEYS, ("price", "installment", "cost"))
        rows, _created = service.execute_new_date(model_ids=[self.model.pk], effective_from=self.day,
                                                  datasets=["installment"], actor=self.root)
        self.assertEqual({item["dataset"]: item["status"] for item in rows[0]["items"]}, {"installment": "create"})
        self.assertEqual(IncentiveCampaign.objects.count(), 2)
        self.assertEqual(DealerRewardCampaign.objects.count(), 1)

    def test_dates_before_today_are_rejected(self):
        yesterday = self.today - timedelta(days=1)
        response = self.preview("date", [self.model], day=yesterday, datasets=["price"])
        self.assertEqual(response.context["stage"], "select")
        self.assertIn("生效日期不可早於今天", " ".join(response.context["errors"]))
        with self.assertRaises(ValidationError):
            service.execute_new_date(model_ids=[self.model.pk], effective_from=yesterday, datasets=["price"],
                                     actor=self.root)
        self.assertEqual(VehiclePriceVersion.objects.count(), 1)

    def test_requires_selection_and_dataset(self):
        response = self.client.post(COPY_URL, {"action": "preview", "mode": "date", "effective_from": self.day.isoformat(),
                                               "row": [self.model.pk]})
        errors = " ".join(response.context["errors"])
        self.assertIn("請至少勾選一項", errors)
        self.assertIn("請至少勾選一個年式", errors)

    def test_tampered_token_is_rejected(self):
        response = self.client.post(COPY_URL, {"action": "commit", "token": "forged"})
        self.assertRedirects(response, COPY_URL, fetch_redirect_response=False)
        self.assertEqual(VehiclePriceVersion.objects.count(), 1)


class CopyPermissionTests(VehicleModelCopyBase):
    def make_user(self, name, grants):
        user = get_user_model().objects.create_user(name, password="Test-Only-123")
        UserAccessState.objects.create(user=user, configured=True)
        for key, operate in grants.items():
            ScreenAccessGrant.objects.create(user=user, screen_key=key, view=True, operate=operate)
        return user

    def test_view_only_user_cannot_post(self):
        self.client.force_login(self.make_user("viewer", {"models": False}))
        self.assertEqual(self.client.get(COPY_URL).status_code, 200)
        self.assertEqual(self.preview("date", [self.model], datasets=["price"]).status_code, 403)
        response = self.client.get(reverse("vehicle_model_price_versions", args=[self.model.pk]))
        self.assertNotContains(response, COPY_URL)

    def test_no_access_without_models_screen(self):
        self.client.force_login(self.make_user("nobody", {"costs": True}))
        self.assertEqual(self.client.get(COPY_URL).status_code, 403)

    def test_dataset_needs_its_own_operate_permission(self):
        self.client.force_login(self.make_user("models-only", {"models": True}))
        listing = self.client.get(COPY_URL)
        allowed = {choice["key"]: choice["allowed"] for choice in listing.context["datasets"]}
        self.assertEqual(allowed, {"price": True, "installment": True, "cost": False})
        response = self.preview("date", [self.model], datasets=["cost"])
        self.assertIn("沒有其中部分資料的操作權限", " ".join(response.context["errors"]))
        # 即使拿到含成本的預覽內容，送出時也會再檢查權限。
        self.client.force_login(self.root)
        token = self.preview("date", [self.model], datasets=["cost"]).context["token"]
        self.client.force_login(get_user_model().objects.get(username="models-only"))
        self.client.post(COPY_URL, {"action": "commit", "token": token})
        self.assertFalse(VehicleSettlementCostRule.objects.filter(effective_from=self.day).exists())

    def test_catalog_copy_is_admin_only(self):
        user = self.make_user("manager", {"models": True, "commissions": True})
        self.client.force_login(user)
        listing = self.client.get(COPY_URL, {"mode": "year"})
        extras = {choice["key"]: choice["allowed"] for choice in listing.context["extras"]}
        self.assertEqual(extras, {"colors": True, "catalog": False, "commission": True,
                                  "incentive_campaigns": False, "reward_campaigns": True})


class NewVersionPrefillTests(VehicleModelCopyBase):
    def test_price_form_prefills_current_version(self):
        # 已有版本時表單預設收起，按「＋ 新增版本」（?new=1）才顯示並帶入目前版本。
        collapsed = self.client.get(reverse("vehicle_model_price_versions", args=[self.model.pk]))
        self.assertNotContains(collapsed, 'class="price-version-form"')
        self.assertContains(collapsed, "＋ 新增版本")
        response = self.client.get(reverse("vehicle_model_price_versions", args=[self.model.pk]), {"new": 1})
        form = response.context["form"]
        self.assertEqual(form.initial["cash_price"], 68000)
        self.assertEqual(form.initial["suggested_price"], 72000)
        self.assertFalse(form.initial["suggested_price_includes_registration"])
        self.assertEqual(form.initial["effective_from"], self.today)  # 預設今天立即生效
        self.assertContains(response, "已帶入")
        # 編輯既有版本時不預填。
        editing = self.client.get(reverse("vehicle_model_price_versions", args=[self.model.pk]), {"edit": self.price.pk})
        self.assertIsNone(editing.context["prefill_version"])

    def test_prefill_moves_past_already_scheduled_version(self):
        VehiclePriceVersion.objects.create(vehicle_model=self.model, cash_price=70000, effective_from=self.day)
        form = self.client.get(reverse("vehicle_model_price_versions", args=[self.model.pk])).context["form"]
        self.assertEqual(form.initial["cash_price"], 70000)
        self.assertEqual(form.initial["effective_from"], self.day + timedelta(days=1))  # 已排定版本的隔天

    def test_cost_form_prefills(self):
        cost = self.client.get(reverse("vehicle_model_settlement_costs", args=[self.model.pk])).context["form"]
        self.assertEqual((cost.initial["amount"], cost.initial["effective_from"]), (56000, self.today))

    def test_installment_form_prefills_options_and_saves_them(self):
        response = self.client.get(reverse("vehicle_installment_plan_list", args=[self.model.pk]))
        formset = response.context["option_formset"]
        self.assertEqual([form.initial.get("periods") for form in formset.forms], [12, 24])
        self.assertEqual(response.context["form"].initial["effective_from"], self.today)
        data = {
            "plan-effective_from": self.day.isoformat(), "plan-announced_on": self.today.isoformat(), "plan-active": "on",
            "options-TOTAL_FORMS": "2", "options-INITIAL_FORMS": "0", "options-MIN_NUM_FORMS": "0", "options-MAX_NUM_FORMS": "1000",
        }
        for index, form in enumerate(formset.forms):
            for name, value in form.initial.items():
                data[f"options-{index}-{name}"] = "" if value is None else str(value)
        self.client.post(reverse("vehicle_installment_plan_list", args=[self.model.pk]), data)
        plan = InstallmentPlanVersion.objects.get(vehicle_model=self.model, effective_from=self.day)
        self.assertEqual(sorted(plan.options.values_list("periods", flat=True)), [12, 24])
