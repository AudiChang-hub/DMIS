"""T-228：報表中心車型篩選改成車種（同名車型合併），車色統計合併同一廣告色依年式分開的車色。"""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import ReportDefinition, SalesOrder, VehicleColor, VehicleModel
from sales.reporting.colors import report_color_name
from sales.reporting.tree_filter import build_tree, expand_cards, tree_chips
from sales.reporting.views import initial_config, publication_key


def order(model, color, month=10):
    return SalesOrder.objects.create(
        source_type="store", order_date=date(2026, month, 2), registration_date=date(2026, month, 3),
        registration_completed_at=timezone.now(), owner_type="company", owner_name="合成車主", owner_id_number="83739807",
        vehicle_model=model, color=color, vehicle_price=10000, actual_balance=10000, calculated_balance=10000,
        payment_type="cash", status="completed")


class FamilyTreeAndColorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", "admin@example.invalid", "Test-Only-123")
        make = VehicleModel.objects.create
        # New NEX 125 兩個型號／年式：篩選樹合併成一項。
        cls.nex_2026 = make(brand="SUZUKI", name="New NEX 125", model_number="UT125XDA", model_year=2026, energy_type="gas")
        cls.nex_2022 = make(brand="SUZUKI", name="New NEX 125", model_number="UT125XZ", model_year=2022, energy_type="gas")
        # Saluto 125：盧卡綠依年式代號拆成兩個車色（T-223 正式站資料），另一個年式也有盧卡綠。
        cls.saluto = make(brand="SUZUKI", name="Saluto 125", model_number="UC125", model_year=2022, energy_type="gas")
        cls.saluto_new = make(brand="SUZUKI", name="Saluto 125", model_number="UC125DA", model_year=2026, energy_type="gas")
        cls.fun = make(brand="eReady", name="Fun", model_number="EV060L", model_year=2023, energy_type="electric")
        color = VehicleColor.objects.create
        cls.luca_d = color(vehicle_model=cls.saluto, name="盧卡綠（UC125D）", code="T94", active=False)
        cls.luca_d2 = color(vehicle_model=cls.saluto, name="盧卡綠（UC125D2）", code="N34", active=False)
        cls.luca_new = color(vehicle_model=cls.saluto_new, name="盧卡綠")
        cls.matte = color(vehicle_model=cls.saluto, name="黑（消光）")
        cls.black = color(vehicle_model=cls.saluto, name="黑")
        nex_white = color(vehicle_model=cls.nex_2026, name="白")
        nex_old_white = color(vehicle_model=cls.nex_2022, name="白")
        fun_white = color(vehicle_model=cls.fun, name="白")
        rows = [(cls.saluto, cls.luca_d), (cls.saluto, cls.luca_d), (cls.saluto, cls.luca_d), (cls.saluto, cls.luca_d2),
                (cls.saluto, cls.luca_d2), (cls.saluto_new, cls.luca_new), (cls.saluto, cls.matte), (cls.saluto, cls.black),
                (cls.nex_2026, nex_white), (cls.nex_2026, nex_white), (cls.nex_2022, nex_old_white), (cls.fun, fun_white)]
        for model, item in rows:
            order(model, item)
        base = {**initial_config(), "audience": "team", "navigation_group": "analysis",
                "reader_layout": "analysis_overview", "include_undated": True}
        bar = {"title": "顏色", "chart": "bar", "dimension": "color", "metric": "count", "formula": "",
               "limit": 100, "sort": "value"}
        cls.color_config = {**base, "title": "車色統計", "cards": [bar]}
        cls.per_model_config = {**base, "title": "車型 X 顏色", "cards": [{**bar, "per_model": True}]}
        cls.population_config = {**base, "title": "性別 X 車型顏色", "include_records": True, "records_mode": "population",
                                 "records_page_size": 100, "records_columns": ["color", "owner_name", "sex", "number"],
                                 "cards": [bar]}
        create = ReportDefinition.objects.create
        cls.color_report = create(draft=cls.color_config, published=cls.color_config, version=1)
        cls.per_model_report = create(draft=cls.per_model_config, published=cls.per_model_config, version=1)
        cls.population_report = create(draft=cls.population_config, published=cls.population_config, version=1)

    def setUp(self):
        self.client.force_login(self.admin)

    def ids(self, *models):
        return [str(model.pk) for model in models]

    def leaf(self, tree, brand, name):
        brand_node = next(node for node in tree["children"] if node["label"] == brand)
        return next(leaf for energy in brand_node["children"] for leaf in energy["children"] if leaf["label"] == name)

    # ---- 車型篩選：同名車種合併 ----
    def test_tree_merges_years_and_model_numbers_into_one_family(self):
        tree = build_tree(self.color_config)
        suzuki = tree["children"][1]
        self.assertEqual(suzuki["label"], "SUZUKI")
        self.assertEqual([leaf["label"] for leaf in suzuki["children"][0]["children"]], ["New NEX 125", "Saluto 125"])
        nex = self.leaf(tree, "SUZUKI", "New NEX 125")
        self.assertEqual(sorted(nex["leaves"], key=int), self.ids(self.nex_2026, self.nex_2022))
        self.assertEqual(nex["count"], 3)  # 2026 兩台＋2022 一台
        self.assertEqual(nex["detail"], "")  # 不再顯示型號與年式
        self.assertEqual(self.leaf(tree, "SUZUKI", "Saluto 125")["count"], 8)
        self.assertEqual(tree["leaf_count"], 3)

    def test_tree_renders_one_item_per_family_with_all_model_inputs(self):
        response = self.client.get(reverse("report_display", args=[self.color_report.pk]))
        html = response.content.decode()
        self.assertEqual(html.count('aria-level="4"'), 3)
        self.assertNotIn("UT125XZ · 2022", html)
        self.assertNotIn("report-tree__detail", html)
        for model in (self.nex_2026, self.nex_2022, self.saluto, self.saluto_new, self.fun):
            self.assertIn(f'name="model" value="{model.pk}" form="report-filter-form" data-tree-input hidden checked', html)
        self.assertIn("全部 3 個車型", html)
        self.assertIn('data-report-tree-rail-sub>3 款', html)

    def test_checking_a_family_selects_all_its_years(self):
        params = {"model": self.ids(self.nex_2026, self.nex_2022), "revision": publication_key(self.color_report)}
        response = self.client.get(reverse("report_display", args=[self.color_report.pk]), params)
        self.assertEqual(response.context["results"][0]["count"], 3)
        tree = response.context["tree_filter"]
        self.assertEqual(self.leaf(tree, "SUZUKI", "New NEX 125")["state"], "checked")
        self.assertEqual(self.leaf(tree, "SUZUKI", "Saluto 125")["state"], "unchecked")
        chips = {chip["label"]: chip["value"] for chip in response.context["active_filters"]}
        self.assertEqual(chips, {"eReady": "已取消勾選", "SUZUKI": "New NEX 125"})

    def test_old_url_with_one_year_keeps_family_mixed(self):
        tree = build_tree(self.color_config, {"model": self.ids(self.nex_2022)})
        nex = self.leaf(tree, "SUZUKI", "New NEX 125")
        self.assertEqual(nex["state"], "mixed")
        self.assertEqual([item["checked"] for item in nex["inputs"]], [True, False] if nex["inputs"][0]["value"] == str(self.nex_2022.pk) else [False, True])
        self.assertEqual(tree_chips(tree, {"model": self.ids(self.nex_2022)})[1]["value"], "New NEX 125")

    # ---- 依勾選車型各一張圖：一個車種一張 ----
    def test_per_model_cards_are_one_per_family(self):
        expanded, info = expand_cards(self.per_model_config, {})
        self.assertEqual([card["title"] for card in expanded["cards"]], ["Saluto 125－顏色", "New NEX 125－顏色", "Fun－顏色"])
        self.assertEqual(sorted(expanded["cards"][0]["vehicle_model"]), sorted([self.saluto.pk, self.saluto_new.pk]))
        self.assertEqual(info["total"], 3)
        response = self.client.get(reverse("report_display", args=[self.per_model_report.pk]))
        saluto = response.context["results"][0]
        self.assertEqual([(row["label"], row["count"]) for row in saluto["rows"]], [("盧卡綠 N34／T94", 6), ("黑", 1), ("黑（消光）", 1)])  # T-231 起標籤帶色碼

    # ---- 車色統計：盧卡綠合併 ----
    def test_color_chart_counts_luca_green_as_one_color(self):
        response = self.client.get(reverse("report_display", args=[self.color_report.pk]))
        rows = {row["label"]: row["count"] for row in response.context["results"][0]["rows"]}
        self.assertEqual(rows, {"盧卡綠 N34／T94": 6, "白": 4, "黑": 1, "黑（消光）": 1})  # T-231 起標籤帶色碼
        luca = next(row for row in response.context["results"][0]["rows"] if row["label"].startswith("盧卡綠"))
        detail = self.client.get(reverse("report_detail", args=[self.color_report.pk, 0]),
                                 {"group": luca["key"], "revision": publication_key(self.color_report)})
        self.assertEqual(detail.context["page_obj"].paginator.count, 6)
        export = self.client.get(reverse("report_export", args=[self.color_report.pk, 0]), {"format": "csv"})
        self.assertIn("盧卡綠 N34／T94,6", export.content.decode().replace("\r", ""))
        self.assertNotIn("UC125D", export.content.decode())

    def test_population_table_merges_color_too(self):
        response = self.client.get(reverse("report_display", args=[self.population_report.pk]))
        colors = {row["cells"][0]["value"]: row["cells"][-1]["value"] for row in response.context["records_rows"]}
        self.assertEqual(colors["盧卡綠 N34／T94"], 6)
        self.assertNotIn("盧卡綠（UC125D）", colors)

    def test_orders_and_color_master_keep_name_and_code(self):
        self.client.get(reverse("report_display", args=[self.color_report.pk]))
        self.luca_d.refresh_from_db()
        self.assertEqual((self.luca_d.name, self.luca_d.label), ("盧卡綠（UC125D）", "盧卡綠（UC125D） T94"))
        self.assertEqual(SalesOrder.objects.filter(color=self.luca_d2).count(), 2)

    def test_report_color_name_only_strips_code_suffix(self):
        self.assertEqual(report_color_name("盧卡綠（UC125D）"), "盧卡綠")
        self.assertEqual(report_color_name("盧卡綠 (UC125D2.D3)"), "盧卡綠")
        self.assertEqual(report_color_name("黑（消光）"), "黑（消光）")
        self.assertEqual(report_color_name("帕瑪森白"), "帕瑪森白")
        self.assertEqual(report_color_name("（W17）"), "（W17）")
