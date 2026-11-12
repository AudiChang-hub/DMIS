"""T-151：大數據分析群組的樹狀勾選篩選（總計 → 品牌 → 能源別 → 車型）。"""
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import ReportDefinition, SalesOrder, VehicleColor, VehicleModel
from sales.reporting.forms import FilterForm
from sales.reporting.tree_filter import build_tree, tree_chips, tree_enabled
from sales.reporting.views import initial_config, publication_key


ROOT = Path(settings.BASE_DIR)


def card(title, scope, dimension="color"):
    return {"title": title, "chart": "bar", "dimension": dimension, "metric": "count", "formula": "",
            "limit": 50, "sort": "value", "fixed_filters": scope}


class TreeFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", "admin@example.invalid", "Test-Only-123")
        make = VehicleModel.objects.create
        cls.fun = make(brand="eReady", name="Fun", model_number="EV060L", energy_type="electric", model_year=2023)
        cls.run_model = make(brand="eReady", name="Run", model_number="EV076S", energy_type="electric", model_year=2022)
        cls.light = make(brand="eReady", name="輕電", model_number="EV010", energy_type="light_electric")
        cls.ezzy = make(brand="GOGORO", name="EZZY", model_number="GE3GS", energy_type="light_electric")
        cls.uq = make(brand="SUZUKI", name="UQ125", model_number="UQ125", energy_type="gas")
        cls.unsold = make(brand="SYM", name="沒賣過", model_number="EV999", energy_type="electric")
        rows = [(cls.fun, 9), (cls.fun, 10), (cls.fun, 10), (cls.run_model, 10), (cls.light, 9),
                (cls.ezzy, 10), (cls.uq, 9), (cls.uq, 10)]
        for index, (model, month) in enumerate(rows):
            color = VehicleColor.objects.create(vehicle_model=model, name=f"色{index}")
            SalesOrder.objects.create(source_type="store", order_date=date(2026, month, 2),
                registration_date=date(2026, month, 3), owner_type="company", owner_name="合成車主",
                owner_id_number="83739807", vehicle_model=model, color=color, vehicle_price=10000,
                actual_balance=10000, calculated_balance=10000, payment_type="cash", status="completed")
        base = {**initial_config(), "audience": "team", "navigation_group": "analysis",
                "reader_layout": "analysis_overview", "include_undated": True}
        # 車型 X 性別類：每張圖各自限定車型，樹只列這些車型。
        cls.carded = {**base, "title": "車型 X 顏色", "cards": [
            card("FUN", {"model_contains": ["EV060"]}), card("RUN", {"model_prefix": ["EV076"]}),
            card("輕電", {"model_exact": ["EV010"]}), card("GOGORO", {"model_exact": ["GE3GS"]})]}
        # 有來源明細：明細只套報表範圍，樹也要列到整份報表的車型。
        cls.with_records = {**cls.carded, "title": "性別 X 車型顏色", "include_records": True,
                            "records_columns": ["registration_date", "color"]}
        cls.report = ReportDefinition.objects.create(draft=cls.carded, published=cls.carded, version=1)
        cls.records_report = ReportDefinition.objects.create(draft=cls.with_records, published=cls.with_records, version=1)
        sales = {**initial_config(), "audience": "team", "navigation_group": "sales"}
        cls.sales_report = ReportDefinition.objects.create(draft=sales, published=sales, version=1)

    def setUp(self):
        self.client.force_login(self.admin)

    def url(self, report=None):
        return reverse("report_display", args=[(report or self.report).pk])

    def ids(self, *models):
        return [str(model.pk) for model in models]

    # ---- 樹狀資料的組成 ----
    def test_tree_is_brand_energy_model_and_lists_only_models_with_data(self):
        tree = build_tree(self.carded)
        self.assertEqual((tree["key"], tree["label"], tree["count"], tree["state"]), ("all", "總計", 6, "checked"))
        self.assertEqual([brand["label"] for brand in tree["children"]], ["eReady", "GOGORO"])
        ereddy = tree["children"][0]
        self.assertEqual([energy["label"] for energy in ereddy["children"]], ["電動車", "輕型電動車"])
        self.assertEqual([leaf["label"] for leaf in ereddy["children"][0]["children"]], ["Fun", "Run"])
        self.assertEqual([leaf["count"] for leaf in ereddy["children"][0]["children"]], [3, 1])
        self.assertEqual(ereddy["children"][0]["children"][0]["detail"], "EV060L · 2023")
        self.assertEqual(ereddy["count"], 5)
        leaves = set(tree["leaves"])
        self.assertNotIn(str(self.uq.pk), leaves)  # 不在任何一張圖的範圍
        self.assertNotIn(str(self.unsold.pk), leaves)  # 沒有資料的節點不顯示
        self.assertEqual([node["level"] for node in (tree, ereddy, ereddy["children"][0], ereddy["children"][0]["children"][0])],
                         [1, 2, 3, 4])

    def test_records_report_tree_covers_whole_report_scope(self):
        tree = build_tree(self.with_records)
        self.assertEqual([brand["label"] for brand in tree["children"]], ["eReady", "GOGORO", "SUZUKI"])
        self.assertEqual(tree["count"], 8)

    def test_counts_follow_other_filters_but_structure_and_tree_selection_do_not(self):
        tree = build_tree(self.carded, {"months": ["2026-09"], "model": self.ids(self.run_model)})
        fun, run = tree["children"][0]["children"][0]["children"]
        self.assertEqual((fun["count"], run["count"]), (1, 0))  # 台數套月份，不套樹本身的勾選
        self.assertEqual((fun["state"], run["state"]), ("unchecked", "checked"))
        self.assertEqual(tree["children"][0]["state"], "mixed")
        self.assertEqual(tree["state"], "mixed")
        self.assertEqual(build_tree(self.carded, {"empty_model": True})["state"], "unchecked")

    def test_only_analysis_group_enables_tree(self):
        self.assertTrue(tree_enabled(self.carded))
        self.assertFalse(tree_enabled({**self.carded, "navigation_group": "sales"}))
        self.assertFalse(tree_enabled({**self.carded, "navigation_group": "custom"}))

    # ---- 勾選結果反映到查詢 ----
    def test_checked_models_filter_charts_records_and_exports(self):
        params = {"model": self.ids(self.fun), "revision": publication_key(self.records_report)}
        response = self.client.get(self.url(self.records_report), params)
        self.assertEqual(response.status_code, 200)
        counts = [result["count"] for result in response.context["results"]]
        self.assertEqual(counts, [3, 0, 0, 0])
        self.assertEqual(response.context["records_page"].paginator.count, 3)
        export = self.client.get(reverse("report_records_export", args=[self.records_report.pk]), params)
        self.assertEqual(export.status_code, 200)
        self.assertEqual(export.content.decode("utf-8-sig").count("\n"), 4 + 3)  # 四行說明＋三筆
        chart = self.client.get(reverse("report_export", args=[self.records_report.pk, 0]), {**params, "format": "csv"})
        self.assertEqual(sum(int(line.split(",")[-1]) for line in chart.content.decode().splitlines()[1:]), 3)
        detail = self.client.get(reverse("report_detail", args=[self.records_report.pk, 0]), params)
        self.assertEqual(detail.context["page_obj"].paginator.count, 3)

    def test_unchecking_everything_shows_no_data(self):
        response = self.client.get(self.url(), {"empty_model": "1"})
        self.assertEqual([result["count"] for result in response.context["results"]], [0, 0, 0, 0])
        self.assertEqual([chip["value"] for chip in response.context["active_filters"]], ["未選取（不顯示資料）"])

    def test_without_model_param_everything_is_selected(self):
        response = self.client.get(self.url())
        self.assertEqual([result["count"] for result in response.context["results"]], [3, 1, 1, 1])
        self.assertEqual(response.context["active_filters"], [])
        self.assertEqual(response.content.decode().count('data-tree-input hidden checked'), 4)

    # ---- 網址保留條件、標籤 ----
    def test_url_state_renders_tree_and_removable_brand_chips(self):
        params = {"model": self.ids(self.fun, self.light), "months": ["2026-10"]}
        response = self.client.get(self.url(), params)
        html = response.content.decode()
        self.assertIn('id="report-filter-form"', html)
        self.assertIn('role="tree"', html)
        self.assertIn('data-tree-key="b:eReady" data-tree-count="3"', html.replace('\n', ''))
        self.assertIn(f'name="model" value="{self.fun.pk}" form="report-filter-form" data-tree-input hidden checked', html)
        self.assertIn(f'name="model" value="{self.run_model.pk}" form="report-filter-form" data-tree-input hidden>', html)
        # 品牌部分勾選：aria-checked=mixed，且自動展開讓人看到勾了哪些。
        self.assertRegex(html, r'data-tree-key="b:eReady"')
        self.assertRegex(html, r'aria-checked="mixed" aria-expanded="true" tabindex="-1" data-tree-key="b:eReady"')
        self.assertRegex(html, r'aria-checked="false" aria-expanded="false" tabindex="-1" data-tree-key="b:GOGORO"')
        chips = {chip["label"]: chip for chip in response.context["active_filters"]}
        self.assertEqual(list(chips), ["領牌年月", "eReady", "GOGORO"])
        self.assertEqual(chips["eReady"]["value"], "不含 Run")
        self.assertEqual(chips["GOGORO"]["value"], "已取消勾選")
        restored = parse_qs(chips["GOGORO"]["remove_query"])
        self.assertEqual(sorted(restored["model"]), sorted(self.ids(self.fun, self.light, self.ezzy)))
        self.assertEqual(restored["months"], ["2026-10"])
        everything = parse_qs(self.client.get(self.url(), {"model": self.ids(self.fun, self.light, self.ezzy)})
                              .context["active_filters"][0]["remove_query"])
        self.assertNotIn("model", everything)  # 恢復後等於全選，網址不再帶車型
        cleared = parse_qs(response.context["clear_filters_query"])
        self.assertNotIn("model", cleared)
        self.assertNotIn("empty_model", cleared)

    def test_chip_tooltip_and_aria_label_name_the_brand_once(self):
        """正式站 2.2.0：標籤提示與報讀文字出現「eReady：eReady：Fun」，品牌重複。"""
        response = self.client.get(self.url(), {"model": self.ids(self.fun, self.light, self.ezzy)})
        html = response.content.decode()
        self.assertIn('aria-label="移除篩選 eReady：不含 Run"', html)
        self.assertIn('title="移除篩選　eReady：不含 Run"', html)
        self.assertNotIn("eReady：eReady", html)

    def test_chip_lists_models_or_whole_energy(self):
        tree = build_tree(self.carded)
        chip = tree_chips(tree, {"model": self.ids(self.light, self.ezzy)})[0]
        self.assertEqual(chip["value"], "輕型電動車（全部）")
        self.assertEqual(tree_chips(tree, {}), [])

    def test_brand_and_energy_fields_are_replaced_only_in_analysis_group(self):
        form = FilterForm({}, config=self.carded, tree_filter=True)
        self.assertNotIn("brand", form.fields)
        self.assertNotIn("energy", form.fields)
        self.assertNotIn("model", [field.name for field in form.advanced_fields()])
        stale = FilterForm({"model": ["999999"]}, config=self.carded, tree_filter=True)
        self.assertTrue(stale.is_valid())  # 舊網址的車型只會查不到，不讓報表出錯
        self.assertFalse(FilterForm({"model": ["abc"]}, config=self.carded, tree_filter=True).is_valid())

    # ---- 其他群組不受影響 ----
    def test_other_groups_keep_existing_filters_and_ignore_model(self):
        url = self.url(self.sales_report)
        plain = self.client.get(url)
        response = self.client.get(url, {"model": self.ids(self.fun), "empty_model": "1"})
        html = response.content.decode()
        self.assertNotIn("data-report-tree", html)
        self.assertNotIn('id="report-filter-form"', html)
        self.assertNotIn("data-report-tree-proxy", html)
        self.assertIn("品牌、能源及其他條件", html)
        self.assertIn("brand", response.context["filter_form"].fields)
        self.assertNotIn("model", response.context["filter_form"].fields)
        self.assertIsNone(response.context["tree_filter"])
        self.assertEqual([r["count"] for r in response.context["results"]], [r["count"] for r in plain.context["results"]])
        self.assertEqual(response.context["active_filters"], [])
        brand = self.client.get(url, {"brand": ["SUZUKI"]})
        self.assertEqual(brand.context["results"][0]["count"], 2)

    def test_draft_preview_keeps_existing_filters(self):
        response = self.client.get(reverse("report_draft_preview", args=[self.report.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("data-report-tree", response.content.decode())
        self.assertIn("brand", response.context["filter_form"].fields)

    def test_frontend_wiring(self):
        interactions = (ROOT / "static/js/report-interactions.js").read_text(encoding="utf-8")
        self.assertIn("'reportTreeProxy' in data", interactions)
        self.assertIn("report-filters-synced", interactions)
        script = (ROOT / "static/js/report-tree-filter.js").read_text(encoding="utf-8")
        for needle in ("formdata", "ArrowRight", "ArrowLeft", "aria-checked", "report-filters-synced", "matchMedia('(max-width: 1280px)')"):
            self.assertIn(needle, script)
        css = (ROOT / "static/css/reporting.css").read_text(encoding="utf-8")
        self.assertIn("@media (max-width: 1280px)", css)
        self.assertIn("@media (min-width: 1280.02px)", css)
