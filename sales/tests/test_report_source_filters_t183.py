"""T-183／T-184：銷售來源單一篩選（來源類型併入）與車行／平台拆成兩個選擇器。"""
import re
from datetime import date

from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import ReportDefinition, SalesOrder, SalesSource, VehicleColor, VehicleModel
from sales.reporting.engine import base_query
from sales.reporting.forms import FilterForm, ReportForm
from sales.reporting.views import initial_config, publication_key


def query(text):
    return QueryDict(text)


class ReportSourceFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", "admin@example.invalid", "Test-Only-123")
        cls.dealer = SalesSource.objects.create(name="甲車行", source_type="dealer")
        cls.platform = SalesSource.objects.create(name="小樹購員購", source_type="platform")
        cls.staff = SalesSource.objects.create(name="文傑", source_type="store")
        cls.friend = SalesSource.objects.create(name="朋友推薦", source_type="store")
        model = VehicleModel.objects.create(brand="SUZUKI", name="來源測試車", energy_type="gas")
        color = VehicleColor.objects.create(vehicle_model=model, name="白")
        for index, (source_type, source) in enumerate([("dealer", cls.dealer), ("dealer", cls.dealer), ("platform", cls.platform),
                                                       ("store", cls.staff), ("store", cls.friend), ("store", None)]):
            SalesOrder.objects.create(source_type=source_type, source=source, order_date=date(2026, 10, 1),
                registration_date=date(2026, 10, 2 + index), registration_completed_at=timezone.now(),
                owner_type="company", owner_name="合成車主", owner_id_number="83739807",
                vehicle_model=model, color=color, vehicle_price=10000, actual_balance=10000,
                calculated_balance=10000, payment_type="cash", status="completed")
        cls.config = {**initial_config(), "audience": "team", "include_records": True}
        cls.report = ReportDefinition.objects.create(draft=cls.config, published=cls.config, version=1)

    def count(self, config, text):
        form = FilterForm(query(text), config=config, reader_layout=config.get("reader_layout", "standard"))
        self.assertTrue(form.is_valid(), form.errors)
        return base_query(config, form.cleaned_data).count()

    def test_source_type_is_no_longer_a_reader_filter_and_label_is_sales_source(self):
        for layout in ("standard", "sales_overview", "dealer_overview", "analysis_overview"):
            with self.subTest(layout=layout):
                form = FilterForm(reader_layout=layout, config={**self.config, "reader_layout": layout})
                self.assertNotIn("source_type", form.fields)
                self.assertEqual(form.fields["legacy_source"].label, "銷售來源")

    def test_store_names_outside_the_list_count_as_store_not_dealer(self):
        self.assertEqual(self.count(self.config, "legacy_source=車行"), 2)
        self.assertEqual(self.count(self.config, "legacy_source=網路平台"), 1)
        self.assertEqual(self.count(self.config, "legacy_source=店內員工"), 1)
        self.assertEqual(self.count(self.config, "legacy_source=馭盛"), 2)

    def test_old_source_type_links_convert_to_the_same_orders(self):
        for source_type, expected in (("store", 3), ("dealer", 2), ("platform", 1)):
            with self.subTest(source_type=source_type):
                form = FilterForm(query(f"source_type={source_type}"), config=self.config)
                self.assertTrue(form.is_valid(), form.errors)
                self.assertNotIn("source_type", form.cleaned_data)
                self.assertEqual(base_query(self.config, form.cleaned_data).count(),
                                 SalesOrder.objects.filter(source_type=source_type).count())
                self.assertEqual(base_query(self.config, form.cleaned_data).count(), expected)
        # 舊網址同時帶兩種條件：取交集；完全不重疊時不顯示資料，不擅自放寬。
        self.assertEqual(self.count(self.config, "source_type=store&legacy_source=店內員工&legacy_source=車行"), 1)
        form = FilterForm(query("source_type=dealer&legacy_source=網路平台"), config=self.config)
        self.assertTrue(form.is_valid())
        self.assertTrue(form.cleaned_data["empty_legacy_source"])
        self.assertEqual(base_query(self.config, form.cleaned_data).count(), 0)
        self.assertEqual(self.count(self.config, "source_type=bogus"), 6)

    def test_old_link_shows_sales_source_chip_not_source_type(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("report_display", args=[self.report.pk]),
                                   {"source_type": "platform", "revision": publication_key(self.report)})
        self.assertEqual(response.status_code, 200)
        chips = {item["label"]: item["value"] for item in response.context["active_filters"]}
        self.assertEqual(chips.get("銷售來源"), "網路平台")
        self.assertNotIn("來源類型", chips)
        self.assertNotContains(response, 'name="source_type"')

    def test_standard_layout_splits_source_into_dealer_and_platform_pickers(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("report_display", args=[self.report.pk]))
        html = response.content.decode()
        self.assertIn('<label for="id_source_dealer">車行</label>', html)
        self.assertIn('<label for="id_source_platform">平台</label>', html)
        dealer = html[html.index('id="id_source_dealer"'):html.index('id="id_source_platform"')]
        self.assertIn(f'value="{self.dealer.pk}"', dealer)
        self.assertNotIn(f'value="{self.platform.pk}"', dealer)
        self.assertNotIn(f'value="{self.staff.pk}"', html)
        self.assertEqual(len(re.findall(r'data-multi-split', html)), 2)
        # 車行／平台名稱篩選維持在進階區，不拆分；T-191 起欄名與圖卡一致。
        self.assertIn('<label for="id_legacy_dealer">車行／平台</label>', html)
        self.assertNotIn('原報表車行／平台名稱', html)

    def test_pickers_share_one_parameter_and_union_their_selections(self):
        dealer, platform = str(self.dealer.pk), str(self.platform.pk)
        self.assertEqual(self.count(self.config, f"source={dealer}"), 2)
        self.assertEqual(self.count(self.config, f"source={dealer}&source={platform}"), 3)
        config = {**self.config, "reader_layout": "sales_overview"}
        self.assertEqual(self.count(config, "legacy_dealer=甲車行&legacy_dealer=小樹購員購"), 3)

    def test_selected_value_outside_both_lists_is_kept(self):
        form = FilterForm(query(f"source={self.staff.pk}"), config=self.config)
        groups = form["source"].split_groups
        self.assertIn(str(self.staff.pk), [value for value, _ in groups[0]["choices"]])

    def test_overview_pickers_group_labels_by_order_source_type(self):
        config = {**self.config, "reader_layout": "analysis_overview"}
        form = FilterForm(config=config, reader_layout="analysis_overview")
        groups = {group["label"]: [value for value, _ in group["choices"]] for group in form["legacy_dealer"].split_groups}
        # T-230：只出現在本店單的「馭盛」放進最上面的「本店」組。
        self.assertEqual(groups, {"本店": ["馭盛"], "車行": ["甲車行"], "平台": ["小樹購員購"]})

    def test_fixed_scope_pages_only_show_their_own_picker(self):
        for layout, scope, label in (("platform_overview", "網路平台", "平台"), ("dealer_overview", "車行", "車行")):
            with self.subTest(layout=layout):
                config = {**self.config, "reader_layout": layout, "fixed_filters": {"legacy_source": [scope]}}
                form = FilterForm(config=config, reader_layout=layout)
                self.assertEqual([group["label"] for group in form["legacy_dealer"].split_groups], [label])

    def test_designer_drops_source_type_but_keeps_it_on_old_settings(self):
        form = ReportForm(initial={**self.config, "fixed_filters": {}})
        self.assertNotIn("fixed_source_type", form.fields)
        self.assertIn("fixed_legacy_source", [field.name for field in form.common_scope_fields()])
        old = ReportForm(initial={**self.config, "fixed_filters": {"source_type": ["dealer"]}})
        self.assertIn("fixed_source_type", old.fields)
        self.assertEqual(old.initial["fixed_source_type"], ["dealer"])

    def test_records_and_csv_header_is_sales_source(self):
        # T-186：明細表頭與 CSV 欄名改為「銷售來源」，內容沿用同一套分類。
        from sales.reporting.records import record_context
        config = {**self.config, "records_columns": ["registration_date", "legacy_sales_source"]}
        context = record_context(config, {})
        self.assertIn("銷售來源", context["records_headers"])
        self.assertNotIn("原報表來源類型", context["records_headers"])
        report = ReportDefinition.objects.create(draft=config, published=config, version=1)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("report_records_export", args=[report.pk]), {"revision": publication_key(report)})
        self.assertEqual(response.status_code, 200)
        text = response.content.decode("utf-8-sig")
        self.assertIn("銷售來源", text)
        self.assertNotIn("原報表來源類型", text)
