"""T-164 第二版：報表目錄依報表中心分組、拖拉調整分組與順序（POST 端點）、新增報表先選起點。"""
import copy
import json

from django.test import Client, TestCase
from django.urls import reverse

from sales.models import ReportDefinition, ReportRevision
from sales.reporting.engine import validate_config
from sales.reporting.source_templates import SOURCE_TEMPLATES
from sales.reporting.starters import STARTERS, starter_config
from sales.tests import test_reporting as fixtures


class ReportCatalogT164Tests(TestCase):
    login = fixtures.ReportingTests.login

    @classmethod
    def setUpTestData(cls):
        fixtures.ReportingTests.setUpTestData.__func__(cls)
        ReportDefinition.objects.all().delete()
        cls.pages = {}
        for name in ("total", "electric", "age-sex", "model-sex"):
            config = SOURCE_TEMPLATES[name]()
            if name == "model-sex":  # 正式站已開啟「依勾選車型各一張圖」，只能放在大數據分析
                config["cards"] = [{**config["cards"][0], "per_model": True}]
                validate_config(config)
            cls.pages[name] = ReportDefinition.objects.create(draft=config, published=copy.deepcopy(config), version=1)
        draft_only = starter_config("trend")
        cls.pages["draft"] = ReportDefinition.objects.create(draft=draft_only, version=1)

    def post(self, pages, client=None):
        return (client or self.client).post(reverse("report_reorder"), json.dumps({"pages": pages}), content_type="application/json")

    def current(self):
        """依目錄目前的順序產生送出的資料。"""
        order = []
        for report in ReportDefinition.objects.all():
            order.append((report.draft.get("navigation_group", "custom"), report.draft.get("page_order", 0), report.pk, report))
        return [{"pk": report.pk, "group": group, "version": report.version} for group, _, _, report in sorted(order, key=lambda item: (["sales", "analysis", "custom"].index(item[0]), item[1], item[2]))]

    def test_catalog_lists_groups_in_reader_order_with_state(self):
        self.login()
        changed = self.pages["electric"]
        changed.draft = {**changed.draft, "title": "電動車銷售統計（調整中）"}
        changed.save()
        html = self.client.get(reverse("report_manage")).content.decode()
        sales = html.index('id="catalog-group-sales"')
        analysis = html.index('id="catalog-group-analysis"')
        custom = html.index('id="catalog-group-custom"')
        self.assertLess(sales, analysis)
        self.assertLess(analysis, custom)
        self.assertLess(html.index("總車輛銷售"), html.index("電動車銷售統計（調整中）"))
        self.assertLess(analysis, html.index("性別 X 年齡"))
        self.assertGreater(html.index('data-pk="%d"' % self.pages["draft"].pk), custom)
        self.assertIn('data-state="changed"', html)
        self.assertIn('data-state="draft"', html)
        for key in STARTERS:
            self.assertIn(f'?start={key}"', html)
        self.assertIn(reverse("report_reorder"), html)

    def test_reorder_updates_draft_and_published_layout_only(self):
        self.login()
        report = self.pages["electric"]
        report.draft = {**report.draft, "description": "草稿中的新說明"}
        report.save()
        published_description = report.published["description"]
        pages = self.current()
        moved = next(page for page in pages if page["pk"] == report.pk)
        pages.remove(moved)
        moved["group"] = "custom"
        pages.append(moved)
        response = self.post(pages)
        self.assertEqual(response.status_code, 200, response.content)
        report.refresh_from_db()
        self.assertEqual(report.draft["navigation_group"], "custom")
        self.assertEqual(report.published["navigation_group"], "custom")
        self.assertEqual(report.draft["page_order"], report.published["page_order"])
        self.assertEqual(report.published["description"], published_description)
        self.assertEqual(report.draft["description"], "草稿中的新說明")
        self.assertEqual(report.version, 2)
        revision = ReportRevision.objects.get(report=report, version=2)
        self.assertEqual(revision.action, "reorder")
        self.assertEqual(response.json()["versions"][str(report.pk)], 2)
        self.assertIn(report.pk, response.json()["changed"])
        validate_config(report.draft)
        validate_config(report.published)
        # 報表中心的側欄跟著更新：電動車銷售統計移到「自訂報表」標題之後
        nav = self.client.get(reverse("report_display", args=[self.pages["total"].pk])).content.decode().split('aria-label="報表頁面"', 1)[1]
        self.assertLess(nav.index("<h2>自訂報表</h2>"), nav.index("電動車銷售統計"))

    def test_reorder_within_group_only_touches_moved_reports(self):
        self.login()
        pages = self.current()
        sales = [page for page in pages if page["group"] == "sales"]
        self.assertEqual([page["pk"] for page in sales], [self.pages["total"].pk, self.pages["electric"].pk])
        swapped = [sales[1], sales[0]] + [page for page in pages if page["group"] != "sales"]
        response = self.post(swapped)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["changed"]), 1)
        self.assertIn(response.json()["changed"][0], [self.pages["total"].pk, self.pages["electric"].pk])
        for name in ("age-sex", "model-sex", "draft"):
            self.assertEqual(ReportDefinition.objects.get(pk=self.pages[name].pk).version, 1)
        self.assertLess(ReportDefinition.objects.get(pk=self.pages["electric"].pk).draft["page_order"],
                        ReportDefinition.objects.get(pk=self.pages["total"].pk).draft["page_order"])
        again = self.post(self.current())
        self.assertEqual(again.json()["changed"], [])

    def test_reorder_rejects_stale_incomplete_invalid_and_forbidden_requests(self):
        self.login()
        pages = self.current()
        before = {report.pk: (report.version, report.draft, report.published) for report in ReportDefinition.objects.all()}
        stale = copy.deepcopy(pages)
        stale[0]["version"] = 99
        self.assertEqual(self.post(stale).status_code, 409)
        self.assertEqual(self.post(pages[:-1]).status_code, 409)
        self.assertEqual(self.post(pages + [dict(pages[0])]).status_code, 400)
        bad_group = copy.deepcopy(pages); bad_group[0]["group"] = "finance"
        self.assertEqual(self.post(bad_group).status_code, 400)
        self.assertEqual(self.client.post(reverse("report_reorder"), "not json", content_type="application/json").status_code, 400)
        # 依車型各一張圖只能留在大數據分析；整批回復，不留下其他報表的變更
        per_model = copy.deepcopy(pages)
        for page in per_model:
            page["group"] = "sales" if page["pk"] == self.pages["model-sex"].pk else page["group"]
        per_model.sort(key=lambda page: page["pk"] != self.pages["electric"].pk)
        response = self.post(per_model)
        self.assertEqual(response.status_code, 400)
        self.assertIn("車型 X 性別", response.json()["error"])
        after = {report.pk: (report.version, report.draft, report.published) for report in ReportDefinition.objects.all()}
        self.assertEqual(after, before)
        self.assertFalse(ReportRevision.objects.filter(action="reorder").exists())
        self.assertEqual(self.client.get(reverse("report_reorder")).status_code, 405)
        for user in (self.user, self.other_admin):
            self.login(user)
            self.assertEqual(self.post(pages).status_code, 403)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(self.post(pages, client).status_code, 403)

    def test_page_order_plan_keeps_existing_values_and_falls_back_to_renumbering(self):
        from sales.reporting.views import plan_page_orders

        def check(entries, most_changed):
            plan = plan_page_orders(entries)
            ordered = [plan[pk] for pk, _ in entries]
            self.assertEqual(ordered, sorted(set(ordered)), entries)
            self.assertTrue(all(0 <= value <= 999 for value in ordered))
            self.assertLessEqual(sum(plan[pk] != value for pk, value in entries), most_changed, (entries, plan))
            return plan

        self.assertEqual(check([(1, 10), (2, 20), (3, 30)], 0), {1: 10, 2: 20, 3: 30})
        check([(2, 20), (1, 10), (3, 30)], 1)
        self.assertEqual(check([(1, 10), (9, None), (2, 20)], 1), {1: 10, 9: 15, 2: 20})
        self.assertEqual(check([(1, 10), (2, 20), (9, None)], 1), {1: 10, 2: 20, 9: 30})
        check([(1, 0), (2, 0), (3, 0)], 2)
        self.assertEqual(check([(1, 10), (9, None), (2, 11)], 3), {1: 10, 9: 20, 2: 30})
        self.assertEqual(check([(1, 990), (9, None), (8, None)], 2), {1: 990, 9: 993, 8: 996})
        self.assertEqual(check([(1, 998), (9, None), (8, None)], 3), {1: 10, 9: 20, 8: 30})
        self.assertEqual(plan_page_orders([]), {})

    def test_starters_are_valid_and_open_in_designer(self):
        self.login()
        for key in STARTERS:
            with self.subTest(starter=key):
                config = starter_config(key)
                validate_config(config)
                self.assertEqual(config["audience"], "admin")
                response = self.client.get(reverse("report_create"), {"start": key})
                self.assertContains(response, f'value="{config["title"]}"')
        self.assertContains(self.client.get(reverse("report_create"), {"start": "<script>"}), 'value="銷售台數分析"')
        from sales.reporting.views import initial_config
        self.assertEqual({**starter_config("overview"), "navigation_group": None}, {**initial_config(), "navigation_group": None})
