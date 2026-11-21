"""T-269 方案 B＋E：常用範本庫（每個範本寫明回答的問題）、分組選單白話名稱、分期公司維度、付款方式條件。全部為合成資料。"""
import copy
import json
from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import InstallmentCompany, ReportDefinition, SalesOrder, SalesSource, VehicleColor, VehicleModel
from sales.reporting.engine import DIMENSIONS, base_query, card_result, scope_labels, validate_config, validate_scope
from sales.reporting.forms import CardForm, designer_dimension_choices
from sales.reporting.starters import STARTERS, starter_choices, starter_config
from sales.reporting.tree_filter import expand_cards
from sales.reporting.views import publication_key
from sales.services.installment_company_match import matching_installment_companies


class Company:
    def __init__(self, name):
        self.name = name


class InstallmentCompanyMatchTests(SimpleTestCase):
    """與 T-266 信封同一套規則：名稱相同優先，否則互相包含；少於 2 字不對應；多家由呼叫端決定。"""

    def test_rules(self):
        companies = [Company("示範融資"), Company("示範融資租賃"), Company("測試分期")]
        names = lambda text: [company.name for company in matching_installment_companies(text, companies)]
        self.assertEqual(names("示範融資"), ["示範融資"])  # 名稱相同優先，不再找包含
        self.assertEqual(names("測試"), ["測試分期"])
        self.assertEqual(names("測試分期股份有限公司"), ["測試分期"])
        self.assertEqual(names("示範"), ["示範融資", "示範融資租賃"])  # 多家：呼叫端不猜
        self.assertEqual(names("測"), [])
        self.assertEqual(names(""), [])
        self.assertEqual(names("其他公司"), [])


class TemplateLibraryT269Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", "admin@example.invalid", "Test-Only-123")
        cls.gas = VehicleModel.objects.create(brand="SUZUKI", name="示範油車", model_number="DEMO125", energy_type="gas")
        cls.ev = VehicleModel.objects.create(brand="eReady", name="示範電車", model_number="EVDEMO", energy_type="electric")
        cls.gas_color = VehicleColor.objects.create(vehicle_model=cls.gas, name="白")
        cls.ev_color = VehicleColor.objects.create(vehicle_model=cls.ev, name="黑")
        cls.dealer = SalesSource.objects.create(name="示範車行", source_type="dealer")
        cls.platform = SalesSource.objects.create(name="示範平台", source_type="platform")
        cls.alpha = InstallmentCompany.objects.create(name="示範融資")
        cls.beta = InstallmentCompany.objects.create(name="測試分期")
        InstallmentCompany.objects.create(name="示範融資租賃")
        InstallmentCompany.objects.create(name="停用分期", active=False)
        # 分期單：主檔 ×2（10 月）、只有文字對到主檔 ×1（11 月，包含）、文字對到停用主檔 ×1、對到兩家 ×1、對不到 ×1、空白 ×1。
        cls.order(cls.gas, cls.gas_color, payment_type="installment", installment_company_master=cls.alpha, installment_company="示範融資")
        cls.order(cls.gas, cls.gas_color, payment_type="installment", installment_company_master=cls.beta, installment_company="測試分期")
        cls.order(cls.ev, cls.ev_color, payment_type="installment", installment_company="測試分期股份有限公司", month=11)
        cls.order(cls.ev, cls.ev_color, payment_type="installment", installment_company="停用分期")
        cls.order(cls.ev, cls.ev_color, payment_type="installment", installment_company="示範")
        cls.order(cls.ev, cls.ev_color, payment_type="installment", installment_company="其他公司")
        cls.order(cls.ev, cls.ev_color, payment_type="installment", installment_company="")
        # 現金單：車行 ×2（油、電）、平台 ×1。
        cls.order(cls.gas, cls.gas_color, source_type="dealer", source=cls.dealer)
        cls.order(cls.ev, cls.ev_color, source_type="dealer", source=cls.dealer)
        cls.order(cls.ev, cls.ev_color, source_type="platform", source=cls.platform)
        # 訂單存檔可能依付款方式整理分期欄位；測試需要的原始狀態直接寫回資料庫。
        for pk, master, text in cls.installments:
            SalesOrder.objects.filter(pk=pk).update(installment_company_master=master, installment_company=text, payment_type="installment")

    installments = []

    @classmethod
    def order(cls, model, color, *, month=10, payment_type="cash", installment_company_master=None, installment_company="", **extra):
        values = dict(source_type="store", order_date=date(2026, month, 2), registration_date=date(2026, month, 3),
                      registration_completed_at=timezone.now(), owner_type="company", owner_name="合成車主", owner_id_number="83739807",
                      vehicle_model=model, color=color, vehicle_price=10000, actual_balance=10000, calculated_balance=10000,
                      payment_type="cash", status="completed")
        values.update(extra)
        created = SalesOrder.objects.create(**values)
        if payment_type == "installment":
            cls.installments.append((created.pk, installment_company_master, installment_company))
        return created

    def setUp(self):
        self.client.force_login(self.admin)

    def result(self, card, config=None):
        config = validate_config({**starter_config("blank"), **(config or {}), "cards": [card]})
        return card_result(config, card, {})

    def test_finance_company_dimension_rules(self):
        card = {"title": "分期公司", "chart": "bar", "dimension": "finance_company", "metric": "count", "formula": "",
                "limit": 200, "sort": "value", "fixed_filters": {"payment_type": ["installment"]}}
        counts = {row["label"]: row["count"] for row in self.result(card)["rows"]}
        # 主檔優先；沒有主檔時文字對到啟用中的主檔；停用、對到兩家、對不到、空白都歸「未填」。
        self.assertEqual(counts, {"示範融資": 1, "測試分期": 2, "未填": 4})

    def finance_report(self):
        """圖 0：分期公司（只算分期單）；圖 1：每月台數，用來接圖 0 的點選連動。"""
        finance = {"title": "分期公司", "chart": "bar", "dimension": "finance_company", "metric": "count", "formula": "",
                   "limit": 200, "sort": "value", "fixed_filters": {"payment_type": ["installment"]}}
        month = {"title": "每月", "chart": "bar", "dimension": "month", "metric": "count", "formula": "", "limit": 200, "sort": "key"}
        config = validate_config({**starter_config("blank"), "title": "分期公司測試", "cards": [finance, month]})
        return ReportDefinition.objects.create(draft=config, published=copy.deepcopy(config), version=1)

    def test_finance_company_drill_down_including_unfilled(self):
        report = self.finance_report()
        url = reverse("report_detail", args=[report.pk, 0])
        for group, expected in ((str(self.alpha.pk), 1), (str(self.beta.pk), 2), ("__none__", 4), ("__all__", 7)):
            with self.subTest(group=group):
                response = self.client.get(url, {"group": group})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["page_obj"].paginator.count, expected)
        # 鍵值格式錯誤要明確拒絕，不當成不限。
        self.assertEqual(self.client.get(url, {"group": "v:測試分期"}).status_code, 400)

    def test_finance_company_focus_cross_filters_other_chart(self):
        report = self.finance_report()
        url = reverse("report_display", args=[report.pk])

        def months(group):
            focus = json.dumps([{"card": 0, "group": group, "grain": ""}])
            # 點選連動必須帶發布版本（既有規則：沒帶 revision 回 409，避免用舊版設定解讀點選）。
            response = self.client.get(url, {"focus": focus, "revision": publication_key(report)})
            self.assertEqual(response.status_code, 200)
            return {row["label"]: row["count"] for row in response.context["results"][1]["rows"]}

        self.assertEqual(months(str(self.beta.pk)), {"2026/10": 1, "2026/11": 1})
        self.assertEqual(months("__none__"), {"2026/10": 4})
        self.assertEqual(months([str(self.alpha.pk), "__none__"]), {"2026/10": 5})

    def test_finance_company_csv_export(self):
        report = self.finance_report()
        csv = self.client.get(reverse("report_export", args=[report.pk, 0])).content.decode("utf-8-sig")
        lines = csv.splitlines()
        self.assertIn("分期公司", lines[0])
        for expected in ("未填,4", "測試分期,2", "示範融資,1"):
            self.assertTrue(any(line.startswith(expected) for line in lines), (expected, lines))

    def test_payment_type_scope(self):
        validate_scope({"payment_type": ["installment", "cash", "card"]})
        with self.assertRaises(ValidationError):
            validate_scope({"payment_type": ["bitcoin"]})
        self.assertEqual(scope_labels({"payment_type": ["installment"]}), ["付款方式：分期"])
        config = {**starter_config("blank"), "fixed_filters": {"payment_type": ["installment"]}}
        self.assertEqual(base_query(config, {}).count(), 7)
        self.assertIn("fixed_payment_type", CardForm().fields)

    def test_every_template_answers_a_question_and_runs(self):
        self.assertGreaterEqual(len(STARTERS), 10)
        for key in ("model_color_age", "dealer_energy", "finance_monthly", "model_sex", "platform_monthly"):
            self.assertIn(key, STARTERS)
        for item in starter_choices():
            with self.subTest(template=item["key"]):
                self.assertTrue(item["question"].strip())
                config, _ = expand_cards(validate_config(starter_config(item["key"])), {})
                for card in config["cards"]:
                    card_result(config, card, {})
        response = self.client.get(reverse("report_manage"))
        for item in starter_choices():
            self.assertContains(response, item["question"])

    def test_template_numbers(self):
        def segments(key):
            config = validate_config(starter_config(key))
            result = card_result(config, config["cards"][0], {})
            return {row["label"]: {segment["label"]: int(segment["value"]) for segment in row["segments"]} for row in result["rows"]}
        self.assertEqual(segments("dealer_energy"), {"示範車行": {"油車": 1, "電車": 1}})
        self.assertEqual(segments("finance_monthly"), {"2026/10": {"示範融資": 1, "測試分期": 1, "未填": 4}, "2026/11": {"測試分期": 1}})
        self.assertEqual(segments("platform_monthly"), {"2026/10": {"示範平台": 1}})
        self.assertEqual(segments("model_sex"), {"SUZUKI／示範油車": {"公司或其他": 3}, "eReady／示範電車": {"公司或其他": 7}})
