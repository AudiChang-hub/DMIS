"""批次調整分期方案：帶入目前方案、各期條件（公司／撥款比例／開辦費）逐期設定、預覽不寫入、依生效日建立新版本與並行保護。"""
import json
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
        """模擬畫面：先帶入目前方案，再套用指定欄位（fee=整台開辦費；p=每期金額、c=公司、r=撥款比例、f=開辦費例外；p60="" 代表清空）。"""
        row = installment_batch.build_rows([model], self.day)[0]
        data = {f"sel_{model.pk}": "1", f"fee_{model.pk}": row["fee"]}
        for cell in row["cells"]:
            periods = cell["periods"]
            data[f"p{periods}_{model.pk}"] = cell["value"]
            data[f"c{periods}_{model.pk}"] = cell["company"]
            data[f"r{periods}_{model.pk}"] = cell["rate"]
            data[f"f{periods}_{model.pk}"] = cell["fee"]
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
        self.assertEqual({cell["periods"]: cell["value"] for cell in a["cells"] if cell["value"]},
                         {12: "6,200", 24: "3,300", 48: "1,800"})
        self.assertEqual([cell["periods"] for cell in a["cells"]], [12, 18, 24, 30, 36, 48, 60])
        cells_b = {cell["periods"]: cell for cell in b["cells"]}
        self.assertEqual((cells_b[12]["company"], cells_b[12]["rate"], cells_b[12]["fee"]), (str(self.hotai.pk), "90.5", "1,500"))
        self.assertEqual((cells_b[24]["company"], cells_b[24]["rate"]), (str(self.yuanxin.pk), ""))
        self.assertEqual(cells_b[24]["note"], "固定撥款 $61,000")
        self.assertEqual(b["extra"], [42])
        self.assertEqual(b["fee"], "0", "整台開辦費取最多期數使用的金額，12 期的 1,500 列為例外")
        self.assertEqual(cells_b[24]["fee"], "")
        self.assertIsNone(c["version"])
        self.assertTrue(all(cell["company"] == "" and cell["value"] == "" for cell in c["cells"]))

    def test_page_lists_models_and_batch_tab_links_here(self):
        response = self.client.get(URL, {"status": "all", "effective_from": self.day.isoformat()})
        self.assertContains(response, "分期甲")
        self.assertContains(response, "期數條件")
        self.assertContains(response, "固定撥款 $61,000")
        self.assertContains(response, "另有 42 期（沿用）")
        self.assertContains(response, 'name="p60_')
        self.assertContains(self.client.get(reverse("vehicle_model_batch")), URL)

    def test_preview_writes_nothing_and_commit_creates_new_version(self):
        before = InstallmentPlanVersion.objects.count()
        response = self.post(
            (self.a, self.grid(self.a, p24="3,250", p48="", p60="1,500", c60=str(self.yuanxin.pk), r60="88",
                               f60="1,500", f12="1,000", f24="1,000")),
            (self.c, self.grid(self.c, p18="4,300", c18=str(self.yuanxin.pk), r18="88",
                               p12="6,100", c12=str(self.yuanxin.pk), r12="88")),
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
        # 同一台車：12、24 期和潤 92%，60 期遠信 88%，開辦費各自不同。
        self.assertEqual([options[p].company for p in (12, 24, 60)], [self.hotai, self.hotai, self.yuanxin])
        self.assertEqual([options[p].expected_disbursement_rate for p in (12, 24, 60)],
                         [Decimal("92"), Decimal("92"), Decimal("88")])
        self.assertEqual([options[p].opening_fee for p in (12, 24, 60)], [1000, 1000, 1500])
        _version, options_c = self.options(self.c)
        self.assertEqual(sorted(options_c), [12, 18])
        self.assertEqual(options_c[18].company, self.yuanxin)
        self.assertEqual(options_c[18].opening_fee, 0)
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

    def test_changing_one_period_terms_switches_to_rate_and_keeps_bonus(self):
        response = self.post((self.b, self.grid(self.b, c24=str(self.hotai.pk), r24="91", f24="800")))
        self.client.post(URL, {"action": "commit", "token": response.context["token"]})
        _version, options = self.options(self.b)
        self.assertEqual(options[24].company, self.hotai)
        self.assertEqual(options[24].opening_fee, 800)
        self.assertEqual(options[24].expected_disbursement_method, "rate")
        self.assertEqual(options[24].expected_disbursement_rate, Decimal("91"))
        self.assertIsNone(options[24].expected_disbursement_fixed_amount)
        self.assertEqual(options[24].extra_disbursement_bonus, 300, "改撥款比例時保留額外撥款獎金")
        self.assertEqual(options[12].expected_disbursement_rate, Decimal("90.5"), "其他期數不受影響")

    def test_car_fee_applies_to_all_periods_and_exceptions_override(self):
        """200cc 以上 SUZUKI：24–36 期和潤免開辦費，48 期以上遠信開辦費 3,500。"""
        hotai, yx = str(self.hotai.pk), str(self.yuanxin.pk)
        values = self.grid(self.c, fee="0",
                           p24="5,200", c24=hotai, r24="92", p36="3,700", c36=hotai, r36="92",
                           p48="2,900", c48=yx, r48="90", f48="3,500", p60="2,400", c60=yx, r60="90", f60="3,500")
        response = self.post((self.c, values))
        self.client.post(URL, {"action": "commit", "token": response.context["token"]})
        _version, options = self.options(self.c)
        self.assertEqual({p: (o.company, o.opening_fee) for p, o in options.items()}, {
            24: (self.hotai, 0), 36: (self.hotai, 0), 48: (self.yuanxin, 3500), 60: (self.yuanxin, 3500)})
        row = installment_batch.build_rows([self.c], self.day + timedelta(days=1))[0]
        self.assertEqual(row["fee"], "0")
        self.assertEqual([cell["fee"] for cell in row["cells"] if cell["periods"] in (48, 60)], ["3,500", "3,500"])

        response = self.post((self.a, self.grid(self.a, fee="1,200")))
        self.client.post(URL, {"action": "commit", "token": response.context["token"]})
        _version, options = self.options(self.a)
        self.assertEqual({o.opening_fee for o in options.values()}, {1200})

    def test_new_periods_need_company_and_rate(self):
        response = self.post((self.c, self.grid(self.c, p12="6,000")))
        self.assertContains(response, "12 期：請選擇分期公司、請填撥款比例")
        response = self.post((self.a, self.grid(self.a, p18="0", p30="abc")))
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
        response = self.post((self.a, self.grid(self.a, p60="1,500", c60=str(self.yuanxin.pk), r60="88")))
        data = {"action": "back", "token": response.context["token"], "row": [str(self.a.pk)], "status": "all"}
        response = self.client.post(URL, data)
        row = response.context["rows"][0]
        self.assertTrue(row["selected"])
        self.assertEqual(row["cells"][-1]["value"], "1,500")
        self.assertEqual((row["cells"][-1]["company"], row["cells"][-1]["rate"]), (str(self.yuanxin.pk), "88"))

    def test_packed_grid_field_is_used_and_unselected_rows_keep_current_plan(self):
        """畫面以單一 JSON 欄位送出勾選列；其他列不送內容，錯誤重顯時仍保留目前方案。"""
        values = self.grid(self.c, p12="6,000")  # 缺公司與比例 → 錯誤重顯
        data = {"action": "preview", "effective_from": self.day.isoformat(), "status": "all",
                "row": [str(self.a.pk), str(self.c.pk)], "grid": json.dumps(values)}
        response = self.client.post(URL, data)
        self.assertContains(response, "12 期：請選擇分期公司、請填撥款比例")
        row_a = next(row for row in response.context["rows"] if row["model"] == self.a)
        self.assertEqual(next(cell["value"] for cell in row_a["cells"] if cell["periods"] == 12), "6,200")
        values = self.grid(self.c, p12="6,000", c12=str(self.hotai.pk), r12="92")
        data["grid"] = json.dumps({**values, "evil": "x"})
        self.assertContains(self.client.post(URL, data), "分期方案：1 個年式將變更")

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
