"""T-165 設計器存檔要「原樣存回」：不重排附加指標，沒有實質變更就不標成有修改。"""
import copy

from django.test import TestCase
from django.urls import reverse

from sales.models import ReportDefinition
from sales.reporting.source_templates import SOURCE_TEMPLATES
from sales.reporting.views import publish_state
from sales.tests import test_reporting as fixtures
from sales.tests.test_report_designer_ux_t164 import browser_payload


class ReportSaveFidelityT165Tests(TestCase):
    login = fixtures.ReportingTests.login

    @classmethod
    def setUpTestData(cls):
        fixtures.ReportingTests.setUpTestData.__func__(cls)

    def publish_template(self, name):
        config = SOURCE_TEMPLATES[name]()
        return ReportDefinition.objects.create(draft=copy.deepcopy(config), published=copy.deepcopy(config), version=1)

    def save_unchanged(self, report, action="save"):
        """照瀏覽器規則送出設計器目前的表單，不改任何欄位。"""
        edit = reverse("report_edit", args=[report.pk])
        response = self.client.post(edit, browser_payload(self.client.get(edit).content.decode(), action))
        self.assertEqual(response.status_code, 302, response.content[:600])
        report.refresh_from_db()
        return report

    def test_additional_metrics_keep_saved_order(self):
        """根因：多選清單依選單順序送出，表單照送出順序存回，傭金與台數獎金兩欄因此對調。"""
        self.login()
        for name in ("electric-count", "gasoline-count"):
            with self.subTest(report=name):
                report = self.publish_template(name)
                expected = report.published["cards"][0]["additional_metrics"]
                self.assertEqual(expected, ["dealer_bonus", "dealer_commission"])
                report = self.save_unchanged(report, "publish")
                self.assertEqual(report.draft["cards"][0]["additional_metrics"], expected)
                self.assertEqual(report.published["cards"][0]["additional_metrics"], expected)
                html = self.client.get(reverse("report_display", args=[report.pk])).content.decode()
                table = html.split('class="report-results', 1)[1]
                self.assertLess(table.index("台數獎金"), table.index("傭金"))

    def test_new_selection_appends_after_existing_order(self):
        self.login()
        report = self.publish_template("electric-count")
        edit = reverse("report_edit", args=[report.pk])
        payload = browser_payload(self.client.get(edit).content.decode(), "save")
        payload["cards-0-additional_metrics"] = ["count", "sale_total", "dealer_commission", "dealer_bonus"]
        payload["cards-0-metric"] = ["average_price"]
        self.assertEqual(self.client.post(edit, payload).status_code, 302)
        report.refresh_from_db()
        self.assertEqual(report.draft["cards"][0]["additional_metrics"], ["dealer_bonus", "dealer_commission", "count", "sale_total"])

    def test_saving_without_changes_is_not_marked_changed(self):
        """根因：存檔時把每個選填欄位都寫成預設值（如 height 520、width 6），範本建立的報表沒有這些鍵，草稿與已發布因此不同。"""
        self.login()
        for name, factory in SOURCE_TEMPLATES.items():
            with self.subTest(report=name):
                report = self.publish_template(name)
                report = self.save_unchanged(report)
                self.assertEqual(report.draft, report.published)
                self.assertEqual(publish_state(report), "published")
        manage = self.client.get(reverse("report_manage")).content.decode()
        self.assertNotIn('data-state="changed"', manage)

    def test_report_without_group_stays_in_custom_group(self):
        """沒有 navigation_group 的報表在報表中心算「自訂報表」；設計器不能預設選成第一項「銷售統計」。"""
        from sales.reporting.views import initial_config
        self.login()
        config = initial_config()
        self.assertNotIn("navigation_group", config)
        report = ReportDefinition.objects.create(draft=copy.deepcopy(config), published=copy.deepcopy(config), version=1)
        report = self.save_unchanged(report)
        self.assertEqual(report.draft, config)
        self.assertEqual(publish_state(report), "published")

    def test_real_change_is_still_marked_changed(self):
        self.login()
        report = self.publish_template("total")
        edit = reverse("report_edit", args=[report.pk])
        payload = browser_payload(self.client.get(edit).content.decode(), "save")
        payload["cards-0-height"] = ["640"]
        self.assertEqual(self.client.post(edit, payload).status_code, 302)
        report.refresh_from_db()
        self.assertEqual(report.draft["cards"][0]["height"], 640)
        self.assertEqual(publish_state(report), "changed")
        payload = browser_payload(self.client.get(edit).content.decode(), "save")
        payload["cards-0-height"] = ["520"]  # 改回預設值也是實際設定，要保留
        self.client.post(edit, payload)
        report.refresh_from_db()
        self.assertEqual(report.draft["cards"][0]["height"], 520)
