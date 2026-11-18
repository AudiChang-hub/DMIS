"""T-151 追加：大數據分析「選到幾種車型就出幾張圖」與一次性解鎖指令。"""
import json
import tempfile
from datetime import date
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

from sales.models import ReportDefinition, SalesOrder, VehicleColor, VehicleModel
from sales.reporting.engine import validate_config
from sales.reporting.forms import CardForm
MODEL_COUNT = 10  # T-240：超過舊上限 8 款，全部出圖
from sales.reporting.views import initial_config, publication_key


ROOT = Path(settings.BASE_DIR)


def order(model, color, **extra):
    values = dict(source_type="store", order_date=date(2026, 10, 2), registration_date=date(2026, 10, 3),
                  owner_type="company", owner_name="合成車主", owner_id_number="83739807", vehicle_model=model, color=color,
                  vehicle_price=10000, actual_balance=10000, calculated_balance=10000, payment_type="cash", status="completed")
    values.update(extra)
    return SalesOrder.objects.create(**values)


class PerModelCardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", "admin@example.invalid", "Test-Only-123")
        cls.models = []
        # 車型 i 有 i+1 台；偶數 eReady、奇數 SUZUKI（T-240 起依品牌、車型名稱排列，不依台數）。
        for index in range(MODEL_COUNT):
            brand, energy = ("SUZUKI", "gas") if index % 2 else ("eReady", "electric")
            model = VehicleModel.objects.create(brand=brand, name=f"車{index:02d}", model_number=f"M{index:02d}", energy_type=energy)
            cls.models.append(model)
            color = VehicleColor.objects.create(vehicle_model=model, name=f"白{index}")
            for _ in range(index + 1):
                order(model, color)
        card = {"title": "性別", "chart": "donut", "dimension": "sex", "metric": "count", "formula": "",
                "limit": 10, "sort": "value", "per_model": True}
        cls.config = {**initial_config(), "title": "車型 X 性別", "audience": "team", "navigation_group": "analysis",
                      "reader_layout": "analysis_overview", "include_undated": True, "cards": [card]}
        cls.report = ReportDefinition.objects.create(draft=cls.config, published=cls.config, version=1)
        sales = {**initial_config(), "audience": "team", "navigation_group": "sales"}
        cls.sales_report = ReportDefinition.objects.create(draft=sales, published=sales, version=1)

    def setUp(self):
        self.client.force_login(self.admin)
        self.url = reverse("report_display", args=[self.report.pk])

    def ids(self, *indexes):
        return [str(self.models[index].pk) for index in indexes]

    def titles(self, response):
        return [result["card"]["title"] for result in response.context["results"]]

    def test_one_and_three_models_give_one_card_each_sorted_by_brand_then_name(self):
        one = self.client.get(self.url, {"model": self.ids(3)})
        self.assertEqual(self.titles(one), ["車03－性別"])
        self.assertEqual(one.context["results"][0]["count"], 4)
        three = self.client.get(self.url, {"model": self.ids(1, 5, 2)})
        self.assertEqual(self.titles(three), ["車02－性別", "車01－性別", "車05－性別"])  # eReady 先、SUZUKI 後
        self.assertEqual([result["count"] for result in three.context["results"]], [3, 2, 6])  # 台數不變
        self.assertContains(three, "勾選的 3 款車型各一張圖，依品牌、車型名稱排列")
        self.assertContains(three, "data-per-model")

    def test_all_models_get_a_card_without_cap(self):
        response = self.client.get(self.url)
        self.assertEqual(self.titles(response), [f"車{index:02d}－性別" for index in (0, 2, 4, 6, 8, 1, 3, 5, 7, 9)])
        self.assertEqual([result["count"] for result in response.context["results"]], [1, 3, 5, 7, 9, 2, 4, 6, 8, 10])
        self.assertEqual(response.context["per_model"], {"total": MODEL_COUNT, "shown": MODEL_COUNT})
        self.assertContains(response, f"勾選的 {MODEL_COUNT} 款車型各一張圖")
        self.assertNotContains(response, "縮小勾選範圍")
        self.assertNotContains(response, "report-per-model-note is-attention")

    def test_cards_beyond_eight_keep_sort_detail_and_chart_selection(self):
        params = {"revision": publication_key(self.report)}
        last = MODEL_COUNT - 1  # 第 10 張＝車09
        detail = self.client.get(reverse("report_detail", args=[self.report.pk, last]), params)
        self.assertEqual(detail.context["page_obj"].paginator.count, 10)
        focus = json.dumps([{"card": last, "group": "v:公司或其他", "grain": ""}])
        response = self.client.get(self.url, {**params, "focus": focus})
        self.assertEqual(response.context["error"], "")
        self.assertEqual(response.context["focus_items"][0]["title"], "車09－性別：公司或其他")
        sorted_last = self.client.get(self.url, {**params, f"sort_{last}": "key"})
        self.assertEqual(sorted_last.context["results"][last]["selected_sort"], "key")

    def test_nothing_checked_shows_notice_without_cards(self):
        response = self.client.get(self.url, {"empty_model": "1"})
        self.assertEqual(response.context["results"], [])
        self.assertContains(response, "目前勾選的車型在這個範圍沒有資料")

    def test_detail_export_and_stale_focus_use_expanded_cards(self):
        params = {"model": self.ids(1, 2), "revision": publication_key(self.report)}
        detail = self.client.get(reverse("report_detail", args=[self.report.pk, 1]), params)
        self.assertEqual(detail.context["page_obj"].paginator.count, 2)  # 第二張＝車01
        export = self.client.get(reverse("report_export", args=[self.report.pk, 0]), {**params, "format": "csv"})
        self.assertEqual(export.status_code, 200)
        self.assertEqual(sum(int(line.split(",")[-1]) for line in export.content.decode().splitlines()[1:]), 3)
        self.assertEqual(self.client.get(reverse("report_detail", args=[self.report.pk, 5]), params).status_code, 404)
        # 點了第二張圖後縮小到一款：失效的點選自動移除，不讓整頁出錯。
        focus = json.dumps([{"card": 1, "group": "v:公司或其他", "grain": ""}])
        response = self.client.get(self.url, {**params, "model": self.ids(2), "focus": focus})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["error"], "")
        self.assertEqual(self.titles(response), ["車02－性別"])

    def test_per_model_only_allowed_for_single_card_analysis_reports(self):
        validate_config(self.config)
        with self.assertRaises(ValidationError):
            validate_config({**self.config, "navigation_group": "sales"})
        with self.assertRaises(ValidationError):
            validate_config({**self.config, "cards": self.config["cards"] * 2})

    def test_designer_keeps_per_model_flag_only_when_set(self):
        self.assertIn("per_model", CardForm().fields)
        views = (ROOT / "sales/reporting/views.py").read_text(encoding="utf-8")
        self.assertIn('**({"per_model": True} if card.cleaned_data.get("per_model") else {})', views)

    def test_other_group_reports_are_not_expanded(self):
        response = self.client.get(reverse("report_display", args=[self.sales_report.pk]))
        self.assertIsNone(response.context["per_model"])
        self.assertEqual(self.titles(response), ["品牌銷售台數", "每月銷售走勢"])
        self.assertNotContains(response, "report-per-model-note")


class UnlockAnalysisCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from sales.reporting.source_templates import SOURCE_TEMPLATES
        cls.admin = get_user_model().objects.create_superuser("admin", "admin@example.invalid", "Test-Only-123")
        for brand, number, energy in (("eReady", "EV060L", "electric"), ("eReady", "EV076S", "electric"), ("SUZUKI", "UQ125", "gas")):
            model = VehicleModel.objects.create(brand=brand, name=number, model_number=number, energy_type=energy)
            order(model, VehicleColor.objects.create(vehicle_model=model, name="白"))
        cls.reports = {}
        for key in ("model-sex", "model-color", "age-sex", "sex-model-color", "electric"):
            config = SOURCE_TEMPLATES[key]()
            cls.reports[key] = ReportDefinition.objects.create(draft=config, published=config, version=1)

    def run_command(self, *args):
        out = StringIO()
        call_command("unlock_analysis_reports", *args, stdout=out)
        return out.getvalue()

    def snapshot(self):
        return {report.pk: (report.version, report.published) for report in ReportDefinition.objects.all()}

    def test_dry_run_changes_nothing(self):
        before = self.snapshot()
        self.assertIn("dry-run", self.run_command())
        self.assertEqual(self.snapshot(), before)

    def test_apply_needs_backup_unlocks_and_restore_reverts(self):
        with self.assertRaises(CommandError):
            self.run_command("--apply")
        electric_before = ReportDefinition.objects.get(pk=self.reports["electric"].pk).published
        with tempfile.TemporaryDirectory() as folder:
            backup = Path(folder) / "backup.json"
            backup.write_text("[]", encoding="utf-8")
            with self.assertRaises(CommandError):
                self.run_command("--apply", "--backup", str(backup))  # 不覆蓋既有備份
            self.assertEqual(ReportDefinition.objects.get(pk=self.reports["model-sex"].pk).version, 1)
            backup.unlink()
            self.run_command("--apply", "--backup", str(backup))
            self.assertEqual([row["pk"] for row in json.loads(backup.read_text(encoding="utf-8"))],
                             sorted(self.reports[key].pk for key in ("model-sex", "model-color", "age-sex", "sex-model-color")))
            sex = ReportDefinition.objects.get(pk=self.reports["model-sex"].pk)
            self.assertEqual((sex.version, sex.draft == sex.published), (2, True))
            self.assertEqual(sex.published["cards"], [{**{key: value for key, value in expected_template_card().items()}}])
            self.assertEqual(sex.revisions.first().action, "publish")
            age = ReportDefinition.objects.get(pk=self.reports["age-sex"].pk)
            self.assertEqual(set(age.published["fixed_filters"]), {"model_presence", "age_scope"})
            self.assertNotIn("EV 開頭、電車", age.published["description"])
            self.client.force_login(self.admin)
            # 性別 X 年齡解除後涵蓋油車（原本只算 EV 開頭的電車）。
            self.assertEqual(self.client.get(reverse("report_display", args=[age.pk])).context["results"][1]["count"], 3)
            self.assertEqual(len(self.client.get(reverse("report_display", args=[sex.pk])).context["results"]), 3)
            self.assertEqual(ReportDefinition.objects.get(pk=self.reports["electric"].pk).published, electric_before)
            self.assertIn("沒有需要解開", self.run_command())  # 可重跑，不會重複改
            self.run_command("--restore", str(backup), "--apply")
        restored = ReportDefinition.objects.get(pk=self.reports["model-sex"].pk)
        self.assertEqual(restored.version, 3)
        self.assertEqual(len(restored.published["cards"]), 4)
        self.assertEqual(restored.revisions.first().action, "restore")


def expected_template_card():
    """解鎖後的範本圖卡：沿用原第一張圖的設定，拿掉車型條件、標題去掉車型前綴、標記依車型展開。"""
    from sales.reporting.source_templates import SOURCE_TEMPLATES
    original = SOURCE_TEMPLATES["model-sex"]()["cards"][0]
    card = {key: value for key, value in original.items() if key != "fixed_filters"}
    card.update(title="性別", per_model=True)
    return card
