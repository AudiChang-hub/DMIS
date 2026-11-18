"""T-234：車行多選依區域分組（沿用車行聯絡資料的縣市順序，未填縣市歸「未分區」），選出的值與篩選結果不變。"""
from datetime import date

from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.forms import DealerRewardCampaignForm, DealerVolumeBonusRuleForm, IncentiveCampaignForm
from sales.models import GiftDistribution, GiftDistributionItem, SalesOrder, SalesSource, Store, VehicleColor, VehicleInventory, VehicleModel
from sales.reporting.engine import base_query
from sales.reporting.forms import FilterForm
from sales.reporting.views import initial_config
from sales.services.dealer_regions import group_choices, option_attrs, report_label_key


def dealer(name, city="", address=""):
    source = SalesSource.objects.create(name=name, source_type=SalesSource.SourceType.DEALER, address=address)
    if city != source.city:  # 地址會推出縣市；測試直接指定
        SalesSource.objects.filter(pk=source.pk).update(city=city)
        source.refresh_from_db()
    return source


class RegionHelperTests(TestCase):
    def test_groups_follow_county_order_and_unassigned_last(self):
        cities = {"a": "新北市", "b": "", "c": "臺北市", "d": "基隆市", "e": "新北市", "f": "火星"}
        groups = group_choices([(key, key.upper()) for key in "abcdef"], cities.get)
        self.assertEqual([(g["label"], g["count"], [v for v, _ in g["choices"]]) for g in groups],
                         [("臺北市", 1, ["c"]), ("新北市", 2, ["a", "e"]), ("基隆市", 1, ["d"]), ("未分區", 2, ["b", "f"])])

    def test_option_attrs_and_report_label_key(self):
        self.assertEqual(option_attrs("臺北市"), {"data-region": "臺北市", "data-region-order": "0"})
        self.assertEqual(option_attrs("")["data-region"], "未分區")
        self.assertEqual(report_label_key(" 大發\t機車 abc "), "大發機車ABC")


class ReportDealerRegionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.taipei = dealer("台北車行", "臺北市")
        cls.newtaipei = dealer("板橋 機車", "新北市")
        cls.nowhere = dealer("無址車行")
        cls.platform = SalesSource.objects.create(name="小樹購員購", source_type="platform")
        cls.yongzhan = SalesSource.objects.create(name="永湛", source_type="store", staff_stores=["yongzhan"])
        model = VehicleModel.objects.create(brand="SUZUKI", name="T234 報表車", energy_type="gas")
        color = VehicleColor.objects.create(vehicle_model=model, name="白")
        rows = [("dealer", cls.taipei), ("dealer", cls.newtaipei), ("dealer", cls.newtaipei), ("dealer", cls.nowhere),
                ("platform", cls.platform), ("store", cls.yongzhan)]
        for index, (source_type, source) in enumerate(rows):
            SalesOrder.objects.create(source_type=source_type, source=source, order_date=date(2026, 10, 1),
                registration_date=date(2026, 10, 2 + index), registration_completed_at=timezone.now(),
                owner_type="company", owner_name="合成車主", owner_id_number="83739807",
                vehicle_model=model, color=color, vehicle_price=10000, actual_balance=10000,
                calculated_balance=10000, payment_type="cash", status="completed")
        cls.config = {**initial_config(), "audience": "team", "include_records": True}

    def dealer_group(self, form, name):
        return next(group for group in form[name].split_groups if group["label"] == "車行")

    def test_overview_dealer_picker_groups_labels_by_region(self):
        config = {**self.config, "reader_layout": "analysis_overview"}
        form = FilterForm(config=config, reader_layout="analysis_overview")
        group = self.dealer_group(form, "legacy_dealer")
        self.assertEqual([(r["label"], [v for v, _ in r["choices"]]) for r in group["regions"]],
                         [("臺北市", ["台北車行"]), ("新北市", ["板橋機車"]), ("未分區", ["無址車行"])])
        self.assertEqual(sorted(v for r in group["regions"] for v, _ in r["choices"]), sorted(v for v, _ in group["choices"]))
        others = [g for g in form["legacy_dealer"].split_groups if g["label"] != "車行"]
        self.assertTrue(others and all("regions" not in g for g in others), "本店、平台不分區")
        self.assertEqual(others[0]["label"], "本店")

    def test_standard_dealer_picker_groups_pks_by_region(self):
        form = FilterForm(config=self.config)
        group = self.dealer_group(form, "source")
        self.assertEqual([(r["label"], [v for v, _ in r["choices"]]) for r in group["regions"]],
                         [("臺北市", [str(self.taipei.pk)]), ("新北市", [str(self.newtaipei.pk)]), ("未分區", [str(self.nowhere.pk)])])

    def test_filter_results_are_unchanged(self):
        config = {**self.config, "reader_layout": "analysis_overview"}
        form = FilterForm(QueryDict("legacy_dealer=板橋機車&legacy_dealer=無址車行"), config=config, reader_layout="analysis_overview")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(base_query(config, form.cleaned_data).count(), 3)
        form = FilterForm(QueryDict(f"source={self.taipei.pk}"), config=self.config)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(base_query(self.config, form.cleaned_data).count(), 1)

    def test_rendered_picker_has_collapsible_regions_with_region_actions(self):
        from django.template.loader import render_to_string
        config = {**self.config, "reader_layout": "analysis_overview"}
        form = FilterForm(QueryDict("legacy_dealer=板橋機車"), config=config, reader_layout="analysis_overview")
        html = render_to_string("sales/reporting/filter_field.html", {"field": form["legacy_dealer"]})
        self.assertIn("data-region-scope", html)
        self.assertEqual(html.count("data-region-group"), 3)
        self.assertIn('<strong>臺北市</strong><small data-region-count>1 家</small>', html)
        self.assertEqual(html.count('data-region-select="all">全選此區'), 3)
        self.assertIn('<input type="checkbox" name="legacy_dealer" value="板橋機車" checked>', html)
        self.assertLess(html.index("本店"), html.index("臺北市"))


class SearchableDealerRegionTests(TestCase):
    def setUp(self):
        self.taipei = dealer("台北車行", "臺北市")
        self.nowhere = dealer("無址車行")

    def assert_region_options(self, html):
        self.assertIn(f'value="{self.taipei.pk}" data-region="臺北市" data-region-order="0"', html)
        self.assertIn(f'value="{self.nowhere.pk}" data-region="未分區" data-region-order="22"', html)

    def test_volume_bonus_and_campaign_dealer_options_carry_region(self):
        for form_class in (DealerVolumeBonusRuleForm, IncentiveCampaignForm, DealerRewardCampaignForm):
            with self.subTest(form=form_class.__name__):
                self.assert_region_options(str(form_class()["dealers"]))

    def test_inventory_location_filter_options_carry_region(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin", password="Local-t234-771!"))
        store = Store.objects.create(name="總店", code="HQ")
        model = VehicleModel.objects.create(brand="SYM", name="JET", model_number="T234")
        color = VehicleColor.objects.create(vehicle_model=model, name="黑")
        for n, location in enumerate((self.taipei, self.nowhere)):
            VehicleInventory.objects.create(vehicle_model=model, color=color, frame_number=f"T234{n}", ownership_store=store,
                                            location_store=store, current_dealer=location)
        html = self.client.get(reverse("inventory_list")).content.decode()
        self.assertIn(f'value="dealer-{self.taipei.pk}" data-region="臺北市" data-region-order="0"', html)
        self.assertIn(f'value="dealer-{self.nowhere.pk}" data-region="未分區" data-region-order="22"', html)


class GiftDealerRegionTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin", password="Local-t234-772!"))
        self.keelung = dealer("基隆車行", "基隆市")
        self.taipei = dealer("台北車行", "臺北市")
        self.activity = GiftDistribution.objects.create(title="年節", created_by="admin")
        self.url = reverse("gift_distribution_detail", args=[self.activity.pk])

    def test_picker_groups_dealers_below_home_stores(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn("data-region-scope", html)
        self.assertLess(html.index("本店：馭盛"), html.index("<strong>臺北市</strong>"))
        self.assertLess(html.index("<strong>臺北市</strong>"), html.index("<strong>基隆市</strong>"))
        self.assertIn(f'<div data-region-item><label><input type="checkbox" name="sources" value="{self.taipei.pk}">台北車行</label></div>', html)

    def test_adding_grouped_dealers_still_uses_their_ids(self):
        self.client.post(self.url, {"action": "add_sources", "sources": [str(self.keelung.pk), str(self.taipei.pk)]})
        self.assertEqual(set(GiftDistributionItem.objects.values_list("recipient", flat=True)), {"基隆車行", "台北車行"})
