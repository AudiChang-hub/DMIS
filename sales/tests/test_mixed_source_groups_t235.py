"""T-235：「車行／平台」混合多選分組（標準版型進階篩選、報表設計器固定條件），網路平台與本店在上、車行依縣市、其餘未分區。
只改顯示，選項的值與篩選結果不變。"""
from datetime import date

from django.http import QueryDict
from django.template.loader import render_to_string
from django.test import TestCase
from django.utils import timezone

from sales.models import SalesOrder, SalesSource, VehicleColor, VehicleModel
from sales.reporting.engine import base_query
from sales.reporting.forms import FilterForm, ReportForm
from sales.reporting.views import initial_config
from sales.services.dealer_regions import group_mixed_choices


def source(name, kind, city=""):
    item = SalesSource.objects.create(name=name, source_type=kind)
    SalesSource.objects.filter(pk=item.pk).update(city=city)
    item.refresh_from_db()
    return item


def summary(groups):
    return [(group["label"], [text for _, text in group["choices"]]) for group in groups]


class MixedGroupHelperTests(TestCase):
    def test_platform_and_home_on_top_dealers_by_county_rest_unassigned(self):
        kinds = {"p": "platform", "y": "store", "z": "store", "s": "store", "a": "dealer", "b": "dealer", "c": "dealer", "x": None}
        cities = {"a": "新北市", "b": "臺北市", "c": ""}
        names = {"p": "示範平台甲", "y": "永湛", "z": "馭盛", "s": "示範員工甲", "a": "板橋", "b": "信義", "c": "無址", "x": "已移除"}
        groups = group_mixed_choices([(key, names[key]) for key in "pyzsabcx"], kinds.get, cities.get)
        self.assertEqual(summary(groups), [("網路平台", ["示範平台甲"]), ("本店", ["馭盛", "永湛"]), ("臺北市", ["信義"]),
                                           ("新北市", ["板橋"]), ("未分區", ["示範員工甲", "無址", "已移除"])])


class MixedSourcePickerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.taipei = source("信義車行", "dealer", "臺北市")
        cls.newtaipei = source("板橋 機車", "dealer", "新北市")
        cls.platform = source("示範平台甲員購", "platform")
        cls.yongzhan = source("永湛", "store")
        cls.staff = source("示範員工甲", "store")
        model = VehicleModel.objects.create(brand="SUZUKI", name="T235 報表車", energy_type="gas")
        color = VehicleColor.objects.create(vehicle_model=model, name="白")
        rows = [("dealer", cls.taipei), ("dealer", cls.newtaipei), ("platform", cls.platform), ("store", cls.yongzhan),
                ("store", cls.staff), ("store", None)]
        for index, (source_type, item) in enumerate(rows):
            SalesOrder.objects.create(source_type=source_type, source=item, order_date=date(2026, 10, 1),
                registration_date=date(2026, 10, 2 + index), registration_completed_at=timezone.now(),
                owner_type="company", owner_name="合成車主", owner_id_number="83739807",
                vehicle_model=model, color=color, vehicle_price=10000, actual_balance=10000,
                calculated_balance=10000, payment_type="cash", status="completed")
        cls.config = {**initial_config(), "audience": "team", "include_records": True}

    def test_standard_reader_mixed_picker_is_grouped_and_covers_all_choices(self):
        form = FilterForm(config=self.config)
        groups = form["legacy_dealer"].regions
        self.assertEqual(summary(groups), [("網路平台", ["示範平台甲員購"]), ("本店", ["馭盛", "永湛"]), ("臺北市", ["信義車行"]),
                                           ("新北市", ["板橋機車"]), ("未分區", ["示範員工甲"])])
        self.assertEqual(sorted(v for g in groups for v, _ in g["choices"]), sorted(v for v, _ in form.fields["legacy_dealer"].choices))

    def test_standard_reader_filter_results_unchanged(self):
        form = FilterForm(QueryDict("legacy_dealer=板橋機車&legacy_dealer=馭盛"), config=self.config)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(base_query(self.config, form.cleaned_data).count(), 2)

    def test_rendered_reader_picker_has_region_groups(self):
        form = FilterForm(QueryDict("legacy_dealer=信義車行"), config=self.config)
        html = render_to_string("sales/reporting/filter_field.html", {"field": form["legacy_dealer"]})
        self.assertIn("data-region-scope", html)
        self.assertEqual(html.count("data-region-group"), 5)
        self.assertLess(html.index("<strong>網路平台</strong>"), html.index("<strong>本店</strong>"))
        self.assertLess(html.index("<strong>本店</strong>"), html.index("<strong>臺北市</strong>"))
        self.assertIn('<input type="checkbox" name="legacy_dealer" value="信義車行" checked>', html)

    def test_overview_layouts_keep_split_pickers_without_mixed_groups(self):
        config = {**self.config, "reader_layout": "analysis_overview"}
        form = FilterForm(config=config, reader_layout="analysis_overview")
        self.assertFalse(getattr(form["legacy_dealer"], "regions", None))
        self.assertTrue(form["legacy_dealer"].split_groups)

    def test_designer_fixed_source_is_grouped_and_keeps_saved_values(self):
        form = ReportForm(initial={**self.config, "fixed_filters": {"source": [str(self.taipei.pk), "999999"]}})
        groups = form["fixed_source"].regions
        labels = [label for label, _ in summary(groups)]
        self.assertEqual(labels[:4], ["網路平台", "本店", "臺北市", "新北市"])
        self.assertEqual(labels[-1], "未分區")
        self.assertIn(str(self.platform.pk), [v for v, _ in groups[0]["choices"]])
        self.assertIn(("999999", "已移除項目 #999999"), groups[-1]["choices"])
        self.assertEqual(sorted(v for g in groups for v, _ in g["choices"]), sorted(v for v, _ in form.fields["fixed_source"].choices))
        html = render_to_string("sales/reporting/filter_field.html", {"field": form["fixed_source"]})
        self.assertIn(f'<input type="checkbox" name="fixed_source" value="{self.taipei.pk}" checked>', html)
        self.assertIn("全選此區", html)
