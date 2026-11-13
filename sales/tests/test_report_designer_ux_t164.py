"""T-164 報表設計工具改版（第一版）：報表頁編輯入口、條件標籤、問句式圖表設定；資料結構不變。"""
import copy
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from sales.models import ReportDefinition, ReportRevision
from sales.reporting.engine import DIMENSIONS, validate_config
from sales.reporting.forms import CardForm, LEGACY_SCOPES
from sales.reporting.source_templates import SOURCE_TEMPLATES
from sales.reporting.views import initial_config
from sales.tests import test_reporting as fixtures


class EditorFormValues(HTMLParser):
    """依瀏覽器規則收集 data-report-editor 表單會送出的欄位（不含 <template> 內的空白圖表）。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values, self.in_form, self.template_depth = [], False, 0
        self.select = self.textarea = None
        self.options = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form" and "data-report-editor" in attrs:
            self.in_form = True
        if not self.in_form:
            return
        if tag == "template":
            self.template_depth += 1
        if self.template_depth:
            return
        name = attrs.get("name")
        if tag == "input" and name:
            kind = attrs.get("type", "text")
            if kind in ("checkbox", "radio"):
                if "checked" in attrs:
                    self.values.append((name, attrs.get("value", "on")))
            elif kind not in ("submit", "button"):
                self.values.append((name, attrs.get("value", "")))
        elif tag == "select" and name:
            self.select, self.options = {"name": name, "multiple": "multiple" in attrs}, []
        elif tag == "option" and self.select is not None:
            self.options.append((attrs.get("value", ""), "selected" in attrs))
        elif tag == "textarea" and name:
            self.textarea = [name, ""]

    def handle_endtag(self, tag):
        if not self.in_form:
            return
        if tag == "template":
            self.template_depth -= 1
        elif tag == "form":
            self.in_form = False
        elif tag == "select" and self.select is not None:
            chosen = [value for value, picked in self.options if picked]
            if not chosen and not self.select["multiple"] and self.options:
                chosen = [self.options[0][0]]
            self.values.extend((self.select["name"], value) for value in chosen)
            self.select = None
        elif tag == "textarea" and self.textarea is not None:
            name, text = self.textarea
            self.values.append((name, text[1:] if text.startswith("\n") else text))
            self.textarea = None

    def handle_data(self, data):
        if self.textarea is not None and not self.template_depth:
            self.textarea[1] += data


def browser_payload(html, action):
    parser = EditorFormValues()
    parser.feed(html)
    payload = {}
    for name, value in parser.values:
        payload.setdefault(name, []).append(value)
    payload["action"] = [action]
    return payload


class ReportDesignerUxT164Tests(TestCase):
    login = fixtures.ReportingTests.login

    @classmethod
    def setUpTestData(cls):
        fixtures.ReportingTests.setUpTestData.__func__(cls)
        config = copy.deepcopy(cls.report.draft)
        config["audience"] = "team"
        ReportDefinition.objects.filter(pk=cls.report.pk).update(draft=config, published=config)
        cls.report.refresh_from_db()

    def test_reader_page_offers_edit_entry_only_to_report_editor(self):
        url = reverse("report_display", args=[self.report.pk])
        self.login()
        response = self.client.get(url + "?months=2026-08")
        edit_url = reverse("report_edit", args=[self.report.pk]) + "?from=" + quote(url + "?months=2026-08", safe="")
        self.assertContains(response, f'href="{edit_url}" data-report-edit-link>編輯此報表</a>', html=False)
        self.login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "data-report-edit-link")
        self.assertNotContains(response, "report-heading-actions")

    def test_designer_returns_to_originating_report_only(self):
        self.login()
        edit = reverse("report_edit", args=[self.report.pk])
        origin = reverse("report_display", args=[self.report.pk]) + "?months=2026-08"
        response = self.client.get(edit, {"from": origin})
        self.assertContains(response, f'name="return_to" value="{origin}"', html=False)
        self.assertContains(response, "報表中心")
        for target in ("https://example.com/reports/1/", "//example.com/reports/1/", "/reports/999/", "/orders/", f"/reports/{self.report.pk}/\\x"):
            with self.subTest(target=target):
                self.assertNotContains(self.client.get(edit, {"from": target}), 'name="return_to"')
        payload = browser_payload(response.content.decode(), "save")
        saved = self.client.post(edit, payload)
        self.assertEqual(saved.status_code, 302)
        self.assertEqual(saved["Location"], edit + "?from=" + quote(origin, safe=""))

    def test_designer_layout_puts_name_scope_and_question_fields_first(self):
        self.login()
        html = self.client.get(reverse("report_edit", args=[self.report.pk])).content.decode()
        head, rest = html.split('<section class="designer-scope"', 1)
        self.assertIn('class="designer-title-input"', head)
        self.assertIn('name="audience"', head)
        self.assertIn('name="navigation_group"', head)
        self.assertIn("data-scope-chips", rest)
        dialog = rest.split("<dialog", 1)[1].split("</dialog>", 1)[0]
        legacy = dialog.split("designer-legacy-scope", 1)[1]
        for key in ("brand", "energy", "source", "model", "legacy_energy"):
            self.assertIn(f'name="fixed_{key}"', dialog.split("designer-legacy-scope", 1)[0])
        for key in LEGACY_SCOPES:
            self.assertIn(f'name="fixed_{key}"', legacy)
        self.assertNotIn("data-property-tab", html)
        self.assertNotIn("data-canvas-zoom", html)
        card = html.split("data-report-card>", 1)[1].split("</section>", 1)[0]
        order = [card.index(f'name="cards-0-{name}"') for name in CardForm.BASIC_FIELDS]
        self.assertEqual(order, sorted(order))
        self.assertLess(order[-1], card.index("designer-card-scope"))
        self.assertLess(card.index("designer-card-scope"), card.index("designer-advanced"))
        self.assertGreater(card.index('name="cards-0-font_size"'), card.index("designer-advanced"))
        script = (Path(settings.BASE_DIR) / "static/js/report-designer.js").read_text(encoding="utf-8")
        self.assertNotIn("[data-focus-workbench]').click()", script)

    def test_dimension_menu_groups_every_dimension_once(self):
        form = CardForm(initial=copy.deepcopy(initial_config()["cards"][0]))
        groups = dict(form.fields["dimension"].choices)
        self.assertEqual(list(groups), ["常用", "沿用原 Excel 報表的分類"])
        keys = [key for options in groups.values() for key, _ in options]
        self.assertCountEqual(keys, list(DIMENSIONS))
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all("比對用" not in label for options in groups.values() for _, label in options))
        self.assertIn(("legacy_motor_type", "車種類別（白牌、綠牌、速克達…）"), groups["常用"])
        series = form.fields["series"].choices
        self.assertEqual(series[0], ("", "不細分"))

    def test_every_official_report_round_trips_unchanged_through_new_designer(self):
        """既有報表在新設計器原樣讀入、照瀏覽器送出後存回，設定 JSON 完全不變。"""
        self.login()
        configs = {"initial": initial_config(), **{name: factory() for name, factory in SOURCE_TEMPLATES.items()}}
        for name, config in configs.items():
            with self.subTest(report=name):
                validate_config(config)
                report = ReportDefinition.objects.create(draft=copy.deepcopy(config), version=1)
                ReportRevision.objects.create(report=report, version=1, action="save", config=config, actor=self.admin)
                edit = reverse("report_edit", args=[report.pk])
                first = self.client.post(edit, browser_payload(self.client.get(edit).content.decode(), "save"))
                self.assertEqual(first.status_code, 302, first.content[:800])
                report.refresh_from_db()
                normalized = copy.deepcopy(report.draft)
                self.assertEqual(normalized, config)  # T-165：原樣存回，不補預設值、不重排附加指標
                second = self.client.post(edit, browser_payload(self.client.get(edit).content.decode(), "save"))
                self.assertEqual(second.status_code, 302)
                report.refresh_from_db()
                self.assertEqual(report.draft, normalized)
                for key in ("title", "audience", "date_basis", "navigation_group", "page_order", "reader_layout", "include_undated", "include_records"):
                    self.assertEqual(normalized.get(key), config.get(key, normalized.get(key)), key)
                self.assertEqual(normalized.get("fixed_filters", {}), config.get("fixed_filters", {}))
                self.assertEqual(len(normalized["cards"]), len(config["cards"]))
                for saved, original in zip(normalized["cards"], config["cards"]):
                    for key, value in original.items():
                        actual = saved.get(key, value) if key == "fixed_filters" and not value else saved.get(key)
                        self.assertEqual(actual, value, (name, key))
