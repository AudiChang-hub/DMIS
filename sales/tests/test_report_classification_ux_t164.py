"""T-164 第三版：車種類別設定改名、待歸類優先、發布前檢查對話框、修正按鈕版面、設計器連結。"""
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from sales.models import ReportClassification
from sales.reporting.classification import apply_change
from sales.tests import test_reporting as fixtures


class ClassificationUxT164Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.ReportingTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.url = reverse("report_classification")
        self.client.force_login(self.admin)

    def state(self):
        return ReportClassification.objects.get(pk=1)

    def test_renamed_everywhere_users_look(self):
        page = self.client.get(self.url).content.decode()
        self.assertIn("<title>車種類別設定", page)
        self.assertIn("<h1>車種類別設定</h1>", page)
        maintenance = self.client.get(reverse("data_maintenance")).content.decode()
        self.assertIn("<h2>車種類別設定</h2>", maintenance)
        self.assertNotIn("報表分類設定", maintenance)
        self.assertIn("前往車種類別設定處理", (Path(settings.BASE_DIR) / "templates/sales/reporting/manage.html").read_text(encoding="utf-8"))
        from sales.services.home_favorites import LINKS
        self.assertEqual(LINKS["report-categories"]["label"], "車種類別設定")

    def test_unclassified_task_comes_first_and_settings_are_collapsed(self):
        page = self.client.get(self.url).content.decode()
        status = page.index('class="classification-status"')
        task = page.index('id="classification-unknown"')
        categories = page.index('id="classification-categories"')
        rules = page.index('id="classification-rules"')
        history = page.index('id="classification-history"')
        self.assertLess(status, task)
        self.assertLess(task, categories)
        self.assertLess(categories, rules)
        self.assertLess(rules, history)
        for section in ("classification-categories", "classification-rules", "classification-history"):
            tag = page[page.index(f'id="{section}"'):].split(">", 1)[0]
            self.assertNotIn(" open", tag, section)
        self.assertNotIn("試算草稿影響", page)
        self.assertNotIn('value="preview"', page)  # 草稿與正式版相同時不顯示發布按鈕
        # 編輯中的類別／規則自動展開
        category = self.state().draft["categories"][0]
        edit = self.client.get(self.url, {"category": category["id"]}).content.decode()
        self.assertIn(' open>', edit[edit.index('id="classification-categories"'):][:120])
        self.assertIn(f'編輯「{category["name"]}」', edit)

    def test_check_and_publish_shows_dialog_with_confirmation(self):
        state = self.state()
        apply_change(state.version, "category", {"id": "", "name": "測試類別", "color": "#123456", "order": 20, "enabled": True}, self.admin)
        page = self.client.get(self.url).content.decode()
        self.assertIn('value="preview">檢查影響並發布</button>', page)
        self.assertIn('data-state="changed"', page)
        response = self.client.post(self.url, {"action": "preview", "version": self.state().version})
        html = response.content.decode()
        start = html.index('id="classification-preview"')
        dialog = html[html.rindex("<dialog", 0, start):html.index("</dialog>", start)]
        self.assertIn("data-publish-dialog open", dialog)
        self.assertIn('name="confirm"', dialog)
        self.assertIn("確認並發布分類", dialog)
        self.assertIn("先不要發布", dialog)

    def test_editor_buttons_are_not_stretched(self):
        css = (Path(settings.BASE_DIR) / "static/css/report-classification.css").read_text(encoding="utf-8")
        editor = css.split(".classification-editor{", 1)[1].split("}", 1)[0]
        self.assertNotIn("grid-template-columns", editor)
        self.assertIn(".classification-editor .form-actions{display:flex;justify-content:flex-end;align-items:center", css)
        self.assertNotIn(".classification-workspace button{", css)
        page = self.client.get(self.url).content.decode()
        form = page[page.index('class="classification-editor"'):]
        form = form[:form.index("</form>")]
        self.assertRegex(form, r'</div>\s*<div class="form-actions"><button class="button primary" name="action" value="category">新增類別到草稿</button></div>$')

    def test_designer_links_motor_type_dimension_to_classification(self):
        page = self.client.get(reverse("report_edit", args=[self.report.pk])).content.decode()
        self.assertIn(f'data-motor-type-hint hidden>車種類別（白牌、綠牌、速克達…）怎麼分，在<a href="{self.url}"', page)
        script = (Path(settings.BASE_DIR) / "static/js/report-designer.js").read_text(encoding="utf-8")
        self.assertIn("'legacy_motor_type'", script)
