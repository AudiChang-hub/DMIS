"""T-231：報表中心的車色標籤寫出色碼「名稱 色碼」；合併的車色列出全部色碼，分組與台數不變。"""
import json
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import ReportDefinition, SalesOrder, VehicleColor, VehicleModel
from sales.reporting.colors import color_code_label
from sales.reporting.views import initial_config, publication_key


def order(model, color):
    return SalesOrder.objects.create(
        source_type="store", order_date=date(2026, 10, 2), registration_date=date(2026, 10, 3),
        registration_completed_at=timezone.now(), owner_type="company", owner_name="合成車主", owner_id_number="83739807",
        vehicle_model=model, color=color, vehicle_price=10000, actual_balance=10000, calculated_balance=10000,
        payment_type="cash", status="completed")


def bar(**extra):
    return {"title": "顏色", "chart": "bar", "dimension": "color", "metric": "count", "formula": "",
            "limit": 100, "sort": "value", **extra}


class ReportColorCodeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", "admin@example.invalid", "Test-Only-123")
        make = VehicleModel.objects.create
        cls.saluto = make(brand="SUZUKI", name="Saluto 125", model_number="UC125", model_year=2022, energy_type="gas")
        cls.nex = make(brand="SUZUKI", name="New NEX 125", model_number="UT125XDA", model_year=2026, energy_type="gas")
        color = VehicleColor.objects.create
        luca_d = color(vehicle_model=cls.saluto, name="盧卡綠（UC125D）", code="T94")
        luca_d2 = color(vehicle_model=cls.saluto, name="盧卡綠（UC125D2）", code="N34")
        saluto_white = color(vehicle_model=cls.saluto, name="白", code="W17")
        nex_white = color(vehicle_model=cls.nex, name="白", code="RB5")
        nex_blue = color(vehicle_model=cls.nex, name="藍")  # 沒有色碼
        for model, item, times in ((cls.saluto, luca_d, 3), (cls.saluto, luca_d2, 2), (cls.saluto, saluto_white, 1),
                                   (cls.nex, nex_white, 2), (cls.nex, nex_blue, 1)):
            for _ in range(times):
                order(model, item)
        base = {**initial_config(), "audience": "team", "include_undated": True}
        create = ReportDefinition.objects.create
        analysis = {**base, "navigation_group": "analysis", "reader_layout": "analysis_overview"}
        cls.color_config = {**analysis, "title": "車色統計", "cards": [bar()]}
        cls.per_model_config = {**analysis, "title": "車型 X 顏色", "cards": [bar(per_model=True)]}
        cls.stacked_config = {**analysis, "title": "性別 X 車型顏色", "include_records": True, "records_mode": "population",
                              "records_page_size": 100, "records_columns": ["color", "owner_name", "sex", "number"],
                              "cards": [bar(chart="stacked", series="sex", series_limit=10, series_other=False, series_sort="value")]}
        table = {"title": "車型 X 車色", "chart": "table", "dimension": "family", "series": "color", "metric": "count",
                 "formula": "", "limit": 100, "sort": "value"}
        cls.table_config = {**base, "navigation_group": "sales", "title": "車色表", "cards": [table]}
        cls.color_report = create(draft=cls.color_config, published=cls.color_config, version=1)
        cls.per_model_report = create(draft=cls.per_model_config, published=cls.per_model_config, version=1)
        cls.stacked_report = create(draft=cls.stacked_config, published=cls.stacked_config, version=1)
        cls.table_report = create(draft=cls.table_config, published=cls.table_config, version=1)

    def setUp(self):
        self.client.force_login(self.admin)

    def show(self, report, **params):
        return self.client.get(reverse("report_display", args=[report.pk]), params)

    def test_color_code_label_lists_all_codes_and_skips_blank(self):
        self.assertEqual(color_code_label("盧卡綠", ["T94", "N34", "T94"]), "盧卡綠 N34／T94")
        self.assertEqual(color_code_label("白", ["", None, " W17 "]), "白 W17")
        self.assertEqual(color_code_label("藍", ["", None]), "藍")

    def test_chart_labels_show_codes_with_same_grouping_and_counts(self):
        rows = self.show(self.color_report).context["results"][0]["rows"]
        self.assertEqual([(row["label"], row["count"]) for row in rows],
                         [("盧卡綠 N34／T94", 5), ("白 RB5／W17", 3), ("藍", 1)])
        self.assertEqual([row["key"] for row in rows], ["v:盧卡綠", "v:白", "v:藍"])  # 分組鍵不變，下鑽與點選照舊

    def test_per_model_chart_only_lists_codes_of_its_family(self):
        results = self.show(self.per_model_report).context["results"]
        labels = {result["card"]["title"]: [row["label"] for row in result["rows"]] for result in results}
        self.assertEqual(labels["Saluto 125－顏色"], ["盧卡綠 N34／T94", "白 W17"])
        self.assertEqual(labels["New NEX 125－顏色"], ["白 RB5", "藍"])

    def test_chart_csv_export_and_detail_use_code_labels(self):
        export = self.client.get(reverse("report_export", args=[self.color_report.pk, 0]), {"format": "csv"})
        text = export.content.decode("utf-8-sig").replace("\r", "")
        self.assertIn("盧卡綠 N34／T94,5", text)
        self.assertIn("藍,1", text)
        detail = self.client.get(reverse("report_detail", args=[self.color_report.pk, 0]),
                                 {"group": "v:盧卡綠", "revision": publication_key(self.color_report)})
        self.assertEqual(detail.context["page_obj"].paginator.count, 5)

    def test_cross_filter_chip_shows_codes(self):
        focus = json.dumps([{"card": 0, "group": "v:盧卡綠", "grain": ""}])
        response = self.show(self.color_report, focus=focus, revision=publication_key(self.color_report))
        self.assertEqual([item["title"] for item in response.context["focus_items"]], ["顏色：盧卡綠 N34／T94"])

    def test_stacked_chart_and_population_table_and_export(self):
        response = self.show(self.stacked_report)
        self.assertEqual([row["label"] for row in response.context["results"][0]["rows"]],
                         ["盧卡綠 N34／T94", "白 RB5／W17", "藍"])
        colors = {row["cells"][0]["value"]: row["cells"][-1]["value"] for row in response.context["records_rows"]}
        self.assertEqual(colors, {"盧卡綠 N34／T94": 5, "白 RB5／W17": 3, "藍": 1})
        export = self.client.get(reverse("report_records_export", args=[self.stacked_report.pk]),
                                 {"revision": publication_key(self.stacked_report)})
        text = export.content.decode("utf-8-sig")
        self.assertIn("盧卡綠 N34／T94,合成車主", text)
        self.assertIn("\n藍,合成車主", text.replace("\r", ""))

    def test_summary_table_series_labels_show_codes(self):
        result = self.show(self.table_report).context["results"][0]
        cells = {tuple(row["dimension_cells"]): row["count"] for row in result["rows"]}
        self.assertEqual(cells[("SUZUKI／Saluto 125", "盧卡綠 N34／T94")], 5)
        self.assertEqual(cells[("SUZUKI／New NEX 125", "白 RB5")], 2)
        self.assertEqual(cells[("SUZUKI／New NEX 125", "藍")], 1)

    def test_color_master_and_orders_unchanged(self):
        self.show(self.color_report)
        self.assertEqual(sorted(VehicleColor.objects.values_list("name", "code")),
                         sorted([("盧卡綠（UC125D）", "T94"), ("盧卡綠（UC125D2）", "N34"), ("白", "W17"), ("白", "RB5"), ("藍", "")]))

    def test_peak_color_tile_keeps_name_large_and_codes_in_sub(self):
        tiles = self.show(self.stacked_report).context["kpis"]
        tile = next(tile for tile in tiles if tile["label"] == "最多的車色")
        self.assertEqual(tile["value"], "盧卡綠")
        self.assertTrue(tile["sub"].startswith("N34／T94 · 5 "), tile["sub"])
