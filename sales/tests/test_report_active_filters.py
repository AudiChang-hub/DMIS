"""T-142：報表中心篩選選了就自動套用，畫面列出目前篩選且每項可單獨移除。"""
from django.utils import timezone
import json
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import ReportDefinition, SalesOrder, SalesSource, VehicleColor, VehicleModel
from sales.reporting.forms import FilterForm
from sales.reporting.views import initial_config, publication_key


ROOT = Path(settings.BASE_DIR)


class ReportActiveFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", "admin@example.invalid", "Test-Only-123")
        cls.a = SalesSource.objects.create(name="甲車行", source_type="dealer")
        cls.b = SalesSource.objects.create(name="乙車行", source_type="dealer")
        cls.suzuki = VehicleModel.objects.create(brand="SUZUKI", name="篩選測試車", energy_type="gas")
        cls.sym = VehicleModel.objects.create(brand="SYM", name="篩選測試車二", energy_type="gas")
        for model, source, month in [(cls.suzuki, cls.a, 9), (cls.suzuki, cls.b, 10), (cls.sym, cls.a, 10)]:
            color = VehicleColor.objects.create(vehicle_model=model, name=f"白{month}{source.pk}")
            SalesOrder.objects.create(source_type="dealer", source=source, order_date=date(2026, month, 2),
                registration_date=date(2026, month, 3), registration_completed_at=timezone.now(),  # 已確認領牌（T-172 A′）
                owner_type="company", owner_name="合成車主", owner_id_number="83739807",
                vehicle_model=model, color=color, vehicle_price=10000, actual_balance=10000,
                calculated_balance=10000, payment_type="cash", status="completed")
        cls.config = {**initial_config(), "audience": "team", "include_records": True}
        cls.report = ReportDefinition.objects.create(draft=cls.config, published=cls.config, version=1)

    def setUp(self):
        self.client.force_login(self.admin)
        self.url = reverse("report_display", args=[self.report.pk])

    def chips(self, response):
        return {item["label"]: item for item in response.context["active_filters"]}

    def test_each_active_filter_is_listed_and_removable_alone(self):
        focus = json.dumps([{"card": 0, "group": "2026-10-01", "grain": "month"}])
        params = {"brand": ["SUZUKI"], "months": ["2026-10"], "source": [str(self.a.pk), str(self.b.pk)],
                  "start": "2026-09-01", "end": "2026-10-31", "revision": publication_key(self.report), "focus": focus}
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200)
        chips = self.chips(response)
        self.assertEqual(list(chips), ["期間", "月份", "車行／平台", "品牌"])
        self.assertEqual(chips["品牌"]["value"], "SUZUKI")
        self.assertEqual(chips["期間"]["value"], "2026/09/01～2026/10/31")
        self.assertEqual(chips["月份"]["value"], "2026/10")
        self.assertEqual(chips["車行／平台"]["value"], "甲車行、乙車行")
        self.assertContains(response, 'data-report-active-filters')
        self.assertContains(response, 'aria-label="移除篩選 品牌：SUZUKI"')
        self.assertContains(response, ">全部清除</a>")

        brand_removed = parse_qs(chips["品牌"]["remove_query"])
        self.assertNotIn("brand", brand_removed)
        self.assertEqual(brand_removed["months"], ["2026-10"])
        self.assertEqual(brand_removed["source"], [str(self.a.pk), str(self.b.pk)])
        self.assertEqual(brand_removed["start"], ["2026-09-01"])
        self.assertEqual(brand_removed["focus"], [focus])  # 圖表點選不跟著被清掉
        self.assertEqual(brand_removed["revision"], [publication_key(self.report)])
        period_removed = parse_qs(chips["期間"]["remove_query"])
        self.assertNotIn("start", period_removed)
        self.assertNotIn("end", period_removed)
        self.assertEqual(period_removed["brand"], ["SUZUKI"])

        cleared = parse_qs(response.context["clear_filters_query"])
        self.assertEqual(set(cleared), {"focus", "revision"})
        only_revision = self.client.get(self.url, {"brand": ["SUZUKI"], "revision": publication_key(self.report)})
        self.assertEqual(only_revision.context["clear_filters_query"], "revision=" + publication_key(self.report))

    def test_removal_link_reloads_with_remaining_filters(self):
        response = self.client.get(self.url, {"brand": ["SUZUKI"], "months": ["2026-10"]})
        self.assertEqual(response.context["results"][0]["count"], 1)
        removed = self.client.get(self.url + "?" + self.chips(response)["品牌"]["remove_query"])
        self.assertEqual(removed.context["results"][0]["count"], 2)
        self.assertEqual(list(self.chips(removed)), ["月份"])
        self.assertNotContains(removed, ">全部清除</a>")  # 只剩一項時用標籤上的 × 即可

    def test_export_and_source_orders_follow_current_filters(self):
        response = self.client.get(self.url, {"brand": ["SUZUKI"], "months": ["2026-10"]})
        self.assertIn("brand=SUZUKI", response.context["query"])
        self.assertIn("months=2026-10", response.context["query"])
        self.assertContains(response, reverse("report_records_export", args=[self.report.pk]) + "?" + response.context["query"].replace("&", "&amp;"))

    def test_no_filter_shows_full_scope_without_apply_button(self):
        response = self.client.get(self.url)
        self.assertEqual(response.context["active_filters"], [])
        self.assertContains(response, "未加條件，顯示報表全部範圍")
        html = response.content.decode()
        form = html[html.index('class="report-panel report-filter"'):html.index("</form>", html.index('class="report-panel report-filter"'))]
        self.assertIn('<noscript><div class="report-filter-actions"><button class="button primary">套用篩選</button></div></noscript>', form)
        self.assertEqual(form.count("套用篩選"), 1)
        self.assertNotIn("清除我的篩選", form)

    def test_overview_empty_selection_is_listed_and_removable(self):
        config = {**self.config, "reader_layout": "sales_overview"}
        report = ReportDefinition.objects.create(draft=config, published=config, version=1)
        url = reverse("report_display", args=[report.pk])
        response = self.client.get(url, {"empty_legacy_source": "1", "legacy_source": ""})
        chips = self.chips(response)
        self.assertEqual(chips["銷售來源"]["value"], "未選取（不顯示資料）")
        removed = parse_qs(chips["銷售來源"]["remove_query"])
        self.assertNotIn("empty_legacy_source", removed)
        response = self.client.get(url, {"legacy_source": ["車行", "網路平台"], "months": ["2026-09", "2026-10"]})
        chips = self.chips(response)
        self.assertEqual(chips["銷售來源"]["value"], "車行、網路平台")
        self.assertEqual(chips["領牌年月"]["value"], "2026/09、2026/10")

    def test_long_multiselect_is_summarised_with_full_title(self):
        extra = [SalesSource.objects.create(name=name, source_type="dealer") for name in ("丙車行", "丁車行", "戊車行")]
        sources = [self.a, self.b, *extra]
        form = FilterForm({"source": [str(source.pk) for source in sources]}, config=self.config)
        items, _ = form.active_filters()
        self.assertEqual(items[0]["value"], "甲車行、乙車行、丙車行 等 5 項")
        self.assertEqual(items[0]["title"], "甲車行、乙車行、丙車行、丁車行、戊車行")

    def test_invalid_filters_list_nothing(self):
        form = FilterForm({"start": "2026-10-31", "end": "2026-09-01"}, config=self.config)
        self.assertEqual(form.active_filters(), ([], ""))

    def test_draft_preview_lists_filters_without_revision(self):
        url = reverse("report_draft_preview", args=[self.report.pk])
        response = self.client.get(url, {"brand": ["SYM"]})
        chips = self.chips(response)
        self.assertEqual(chips["品牌"]["value"], "SYM")
        self.assertNotIn("revision", parse_qs(chips["品牌"]["remove_query"]))
        self.assertEqual(response.context["results"][0]["count"], 1)

    def test_auto_apply_is_shared_by_every_report_page(self):
        reader = (ROOT / "templates/sales/reporting/reader_filters.html").read_text(encoding="utf-8")
        self.assertIn("{% include 'sales/reporting/active_filters.html' %}", reader)
        for template in ("display.html", "draft_preview.html"):
            self.assertIn("{% include 'sales/reporting/reader_filters.html' %}",
                          (ROOT / "templates/sales/reporting" / template).read_text(encoding="utf-8"))
        script = (ROOT / "static/js/report-interactions.js").read_text(encoding="utf-8")
        self.assertIn('"[data-report-active-filters]"', script)  # 原地更新時一併換新目前篩選
        self.assertIn("reportAutoSubmitFilters(document.querySelector('.report-filter'))", script)
        self.assertNotIn("if (overview) reader.querySelector('.report-filter').addEventListener('change'", script)
