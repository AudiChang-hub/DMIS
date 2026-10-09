"""批次調整分期方案：帶入目前方案、預覽不寫入、依生效日建立新版本、保留未改的撥款設定與並行保護。"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import (
    InstallmentCompany,
    InstallmentPlanOption,
    InstallmentPlanVersion,
    UserAccountAuditLog,
    VehicleModel,
)
from sales.services import installment_batch
from sales.services.installment_plan import resolve_installment_plan_version
from sales.services.vehicle_model_copy import first_of_next_month

URL = reverse("vehicle_model_installment_batch")
FIXED = InstallmentPlanOption.ExpectedDisbursementMethod.FIXED


class InstallmentBatchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = get_user_model().objects.create_superuser("admin", password="Test-Only-123")
        cls.today = timezone.localdate()
        cls.start = cls.today - timedelta(days=30)
        cls.day = first_of_next_month(cls.today)
        cls.hotai = InstallmentCompany.objects.create(name="和潤")
        cls.yuanxin = InstallmentCompany.objects.create(name="遠信")
        cls.a = cls.make_model("分期甲")
        cls.b = cls.make_model("分期乙")
        cls.c = cls.make_model("分期丙")  # 尚未設定分期
        cls.version_a = InstallmentPlanVersion.objects.create(vehicle_model=cls.a, effective_from=cls.start)
        for periods, monthly in ((12, 6200), (24, 3300), (48, 1800)):
            InstallmentPlanOption.objects.create(
                version=cls.version_a, periods=periods, monthly_amount=monthly, company=cls.hotai,
                opening_fee=0, expected_disbursement_rate=Decimal("92"),
            )
        # 乙：各期公司與開辦費不同，24 期是固定撥款加獎金，另有表格外的 42 期。
        cls.version_b = InstallmentPlanVersion.objects.create(vehicle_model=cls.b, effective_from=cls.start)
        InstallmentPlanOption.objects.create(
            version=cls.version_b, periods=12, monthly_amount=6500, company=cls.hotai, opening_fee=1500,
            expected_disbursement_rate=Decimal("90.5"),
        )
        InstallmentPlanOption.objects.create(
            version=cls.version_b, periods=24, monthly_amount=3500, company=cls.yuanxin, opening_fee=0,
            expected_disbursement_method=FIXED, expected_disbursement_fixed_amount=61000, extra_disbursement_bonus=300,
        )
        InstallmentPlanOption.objects.create(
            version=cls.version_b, periods=42, monthly_amount=2200, company=cls.hotai, opening_fee=0,
            expected_disbursement_rate=Decimal("90"),
        )

    @classmethod
    def make_model(cls, name):
        return VehicleModel.objects.create(
            brand="SUZUKI", name=name, model_number=name, model_year=2026,
            model_code=VehicleModel.ModelType.CBS_DISC, energy_type=VehicleModel.EnergyType.GAS, displacement_cc=125,
        )

    def setUp(self):
        self.client.force_login(self.root)

    def grid(self, model, **values):
        """模擬畫面：先帶入目前方案，再套用指定欄位（p60="" 代表清空）。"""
        row = installment_batch.build_rows([model], self.day)[0]
        data = {f"sel_{model.pk}": "1", f"company_{model.pk}": row["inputs"]["company"],
                f"fee_{model.pk}": row["inputs"]["fee"], f"rate_{model.pk}": row["inputs"]["rate"]}
        for cell in row["cells"]:
            data[f"p{cell['periods']}_{model.pk}"] = cell["value"]
        for key, value in values.items():
            data[f"{key}_{model.pk}"] = value
        return data

    def post(self, *models_data, action="preview"):
        data = {"action": action, "effective_from": self.day.isoformat(), "status": "all"}
        rows = []
        for model, values in models_data:
            rows.append(str(model.pk))
            data.update(values)
        data["row"] = rows
        return self.client.post(URL, data)

    def options(self, model):
        version = resolve_installment_plan_version(model.pk, self.day)
        return version, {option.periods: option for option in version.options.select_related("company")}

    def test_rows_prefill_current_plan_and_flag_mixed_values(self):
        rows = {row["model"].pk: row for row in installment_batch.build_rows([self.a, self.b, self.c], self.day)}
        a, b, c = rows[self.a.pk], rows[self.b.pk], rows[self.c.pk]
        self.assertEqual(a["inputs"], {"company": str(self.hotai.pk), "fee": "0", "rate": "92"})
        self.assertEqual({cell["periods"]: cell["value"] for cell in a["cells"] if cell["value"]},
                         {12: "6,200", 24: "3,300", 48: "1,800"})
        self.assertEqual([cell["periods"] for cell in a["cells"]], [6, 12, 18, 24, 30, 36, 48, 60])
        self.assertTrue(b["summary"]["company_mixed"])
        self.assertTrue(b["summary"]["fee_mixed"])
        self.assertTrue(b["summary"]["rate_mixed"])
        self.assertEqual(b["summary"]["extra"], [42])
        self.assertIsNone(c["version"])
        self.assertEqual(c["inputs"], {"company": "", "fee": "", "rate": ""})

    def test_page_lists_models_and_batch_tab_links_here(self):
        response = self.client.get(URL, {"status": "all", "effective_from": self.day.isoformat()})
        self.assertContains(response, "分期甲")
        self.assertContains(response, "各期不同（維持）")
        self.assertContains(response, "另有 42 期（沿用）")
        self.assertContains(response, 'name="p60_')
        self.assertContains(self.client.get(reverse("vehicle_model_batch")), URL)

    def test_preview_writes_nothing_and_commit_creates_new_version(self):
        before = InstallmentPlanVersion.objects.count()
        response = self.post(
            (self.a, self.grid(self.a, p24="3,250", p48="", p60="1,500", fee="1,000")),
            (self.c, self.grid(self.c, company=str(self.yuanxin.pk), rate="88", p6="12,000", p12="6,100")),
        )
        self.assertContains(response, "分期方案：2 個年式將變更")
        self.assertContains(response, "新增")
        self.assertContains(response, "移除")
        self.assertEqual(InstallmentPlanVersion.objects.count(), before)

        response = self.client.post(URL, {"action": "commit", "token": response.context["token"]}, follow=True)
        self.assertContains(response, "已調整 2 個年式的分期方案")
        version, options = self.options(self.a)
        self.assertEqual(version.effective_from, self.day)
        self.assertEqual(sorted(options), [12, 24, 60])
        self.assertEqual(options[24].monthly_amount, 3250)
        self.assertEqual(options[60].monthly_amount, 1500)
        self.assertTrue(all(option.opening_fee == 1000 for option in options.values()))
        self.assertTrue(all(option.expected_disbursement_rate == Decimal("92") for option in options.values()))
        _version, options_c = self.options(self.c)
        self.assertEqual(sorted(options_c), [6, 12])
        self.assertEqual(options_c[6].company, self.yuanxin)
        self.assertEqual(options_c[6].opening_fee, 0)
        # 舊版本保留，今天下單仍用舊方案。
        self.assertEqual(resolve_installment_plan_version(self.a.pk, self.today), self.version_a)
        self.assertEqual(self.version_a.options.count(), 3)
        log = UserAccountAuditLog.objects.get(actor=self.root, description__startswith="批次調整分期方案")
        self.assertEqual(log.metadata["tool"], "installment_batch")

    def test_mixed_rows_keep_each_period_settings_unless_changed(self):
        response = self.post((self.b, self.grid(self.b, p12="6,300")))
        self.client.post(URL, {"action": "commit", "token": response.context["token"]})
        _version, options = self.options(self.b)
        self.assertEqual(sorted(options), [12, 24, 42])
        self.assertEqual(options[12].monthly_amount, 6300)
        self.assertEqual(options[12].opening_fee, 1500)
        self.assertEqual(options[24].company, self.yuanxin)
        self.assertEqual(options[24].expected_disbursement_method, FIXED)
        self.assertEqual(options[24].expected_disbursement_fixed_amount, 61000)
        self.assertEqual(options[24].extra_disbursement_bonus, 300)
        self.assertEqual(options[42].monthly_amount, 2200)

    def test_setting_company_fee_and_rate_applies_to_all_periods(self):
        response = self.post((self.b, self.grid(self.b, company=str(self.hotai.pk), fee="0", rate="91")))
        self.client.post(URL, {"action": "commit", "token": response.context["token"]})
        _version, options = self.options(self.b)
        for option in options.values():
            self.assertEqual(option.company, self.hotai)
            self.assertEqual(option.opening_fee, 0)
            self.assertEqual(option.expected_disbursement_method, "rate")
            self.assertEqual(option.expected_disbursement_rate, Decimal("91"))
        self.assertEqual(options[24].extra_disbursement_bonus, 300, "改撥款比例時保留額外撥款獎金")

    def test_new_periods_need_company_and_rate(self):
        response = self.post((self.c, self.grid(self.c, p12="6,000")))
        self.assertContains(response, "請選擇分期公司")
        self.assertContains(response, "新增期數請填撥款比例")
        response = self.post((self.a, self.grid(self.a, p6="0", p18="abc")))
        self.assertContains(response, "每期金額需大於 0")
        self.assertContains(response, "請輸入數字")
        self.assertFalse(InstallmentPlanVersion.objects.filter(effective_from=self.day).exists())

    def test_unchanged_rows_are_not_previewed(self):
        response = self.post((self.a, self.grid(self.a)))
        self.assertContains(response, "沒有任何變更")

    def test_clearing_every_period_stops_installments_from_that_day(self):
        cleared = {f"p{periods}": "" for periods in installment_batch.PERIODS}
        response = self.post((self.a, self.grid(self.a, **cleared)))
        self.assertContains(response, "不會提供分期")
        self.client.post(URL, {"action": "commit", "token": response.context["token"]})
        version, options = self.options(self.a)
        self.assertEqual(version.effective_from, self.day)
        self.assertEqual(options, {})

    def test_model_with_version_on_same_day_is_locked(self):
        InstallmentPlanVersion.objects.create(vehicle_model=self.a, effective_from=self.day)
        row = installment_batch.build_rows([self.a], self.day)[0]
        self.assertIn("已有版本", row["locked"])
        response = self.post((self.a, self.grid(self.a, p24="3,000")))
        self.assertContains(response, "沒有任何變更")

    def test_commit_refuses_when_plan_changed_after_preview(self):
        response = self.post((self.a, self.grid(self.a, p24="3,250")))
        InstallmentPlanOption.objects.filter(version=self.version_a, periods=12).update(monthly_amount=6100)
        response = self.client.post(URL, {"action": "commit", "token": response.context["token"]}, follow=True)
        self.assertContains(response, "目前方案已變更")
        self.assertFalse(InstallmentPlanVersion.objects.filter(effective_from=self.day).exists())
        with self.assertRaises(ValidationError):
            installment_batch.commit_changes(changes=[], effective_from=self.today - timedelta(days=1), actor=self.root)

    def test_back_restores_inputs(self):
        response = self.post((self.a, self.grid(self.a, p60="1,500")))
        data = {"action": "back", "token": response.context["token"], "row": [str(self.a.pk)], "status": "all"}
        response = self.client.post(URL, data)
        row = response.context["rows"][0]
        self.assertTrue(row["selected"])
        self.assertEqual(row["cells"][-1]["value"], "1,500")

    def test_view_only_user_cannot_submit(self):
        staff = get_user_model().objects.create_user("viewer", password="Test-Only-123")
        UserAccessState.objects.create(user=staff, configured=True)
        ScreenAccessGrant.objects.create(user=staff, screen_key="models", view=True, operate=False)
        self.client.force_login(staff)
        page = self.client.get(URL, {"status": "all"})
        self.assertContains(page, "你只有查看分期方案的權限")
        response = self.post((self.a, self.grid(self.a, p24="3,000")))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(InstallmentPlanVersion.objects.filter(effective_from=self.day).exists())
