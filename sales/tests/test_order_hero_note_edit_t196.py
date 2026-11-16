"""T-196（使用者 2026-11-16：「這個備註要直接可以在這裡修改」）：訂單頁首便條可直接編輯。

便條是訂單表單「備註」欄（SalesOrder.note）的代理：在便條上打字會寫進訂單表單的同一欄，交給訂單頁既有的自動儲存
（order_edit：驗證、交易、版本號衝突保護、修改紀錄）。可以改訂單內容的人才可編輯，其他人維持唯讀；空白時給「新增備註」。
"""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import OrderChange
from sales.tests import test_completed_order_corrections as correction_tests
from sales.tests.test_order_hero_note_t175 import hero

WORKSPACE = {"HTTP_X_ORDER_WORKSPACE": "1", "HTTP_ACCEPT": "application/json"}


def sticky(page):
    start = page.index('id="order-hero-note"')
    start = page.rindex("<aside", 0, start)
    return page[start:page.index("</aside>", start)]


class EditableHeroNoteTests(TestCase):
    setUpTestData = classmethod(correction_tests.CompletedOrderCorrectionTests.setUpTestData.__func__)
    setUp = correction_tests.CompletedOrderCorrectionTests.setUp
    order = correction_tests.CompletedOrderCorrectionTests.order
    payload = correction_tests.CompletedOrderCorrectionTests.payload

    def page(self, order):
        return self.client.get(reverse("order_detail", args=[order.pk])).content.decode()

    def test_editor_gets_an_editable_note_linked_to_the_order_form_field(self):
        page = self.page(self.order(note="客人週六來牽車"))
        note = sticky(page)
        self.assertIn("data-hero-note-editable", note)
        self.assertIn('data-hero-note-input', note)
        self.assertIn(">客人週六來牽車</textarea>", note)
        self.assertNotIn('name="', note)  # 便條本身不送出，存檔一律走訂單表單的 note 欄
        self.assertIn('data-hero-note-field="note"', note)
        self.assertIn('role="status"', note)
        # 訂單表單上真正存檔的「備註」欄仍在。
        self.assertIn('name="note"', page.split('id="order-form"', 1)[1])

    def test_empty_note_offers_an_add_state_for_editors(self):
        note = sticky(self.page(self.order(note="")))
        self.assertIn("is-empty", note)
        self.assertNotIn(" hidden", note.split(">", 1)[0])
        self.assertIn('placeholder="＋ 新增備註"', note)

    def test_viewer_without_edit_rights_keeps_the_read_only_note(self):
        order = self.order(note="只能看")
        viewer = get_user_model().objects.create_user("note-viewer", password="test-only-123")
        UserAccessState.objects.create(user=viewer, configured=True)
        ScreenAccessGrant.objects.create(user=viewer, screen_key="orders", view=True)
        self.client.force_login(viewer)
        response = self.client.get(reverse("order_detail", args=[order.pk]))
        self.assertEqual(response.status_code, 200)
        note = sticky(response.content.decode())
        self.assertNotIn("data-hero-note-editable", note)
        self.assertNotIn("<textarea", note)
        self.assertIn(">只能看</p>", note)
        empty = self.order(note="")
        self.assertIn(" hidden", sticky(self.client.get(reverse("order_detail", args=[empty.pk])).content.decode()).split(">", 1)[0])

    def test_saving_through_order_autosave_records_change_and_bumps_revision(self):
        order = self.order(note="舊備註")
        revision = order.revision
        response = self.client.post(reverse("order_edit", args=[order.pk]), self.payload(order, note="改成週日交車"), **WORKSPACE)
        self.assertEqual(response.status_code, 200, response.content[:500])
        self.assertTrue(response.json()["ok"])
        order.refresh_from_db()
        self.assertEqual((order.note, order.revision), ("改成週日交車", revision + 1))
        self.assertEqual(response.json()["sync"]["order"]["note"], "改成週日交車")
        change = OrderChange.objects.filter(order=order).latest("pk")
        self.assertEqual(change.changes["備註"], {"before": "舊備註", "after": "改成週日交車"})

    def test_stale_revision_is_rejected_and_keeps_the_saved_note(self):
        order = self.order(note="原本")
        stale = self.payload(order, note="過期的修改")
        self.client.post(reverse("order_edit", args=[order.pk]), self.payload(order, note="別人先改"), **WORKSPACE)
        response = self.client.post(reverse("order_edit", args=[order.pk]), stale, **WORKSPACE)
        self.assertEqual(response.status_code, 409)
        self.assertIn("您的輸入仍保留", response.json()["error"])
        order.refresh_from_db()
        self.assertEqual(order.note, "別人先改")

    def test_read_only_markup_is_unchanged_from_t175(self):
        # 唯讀便條（沒有修改權限、自動儲存回應的 hero_note_html）與 T-175 相同。
        from django.template.loader import render_to_string
        html = render_to_string("sales/_order_hero_note.html", {"order": self.order(note="原樣")})
        self.assertIn('<p class="order-hero-note__text" id="order-hero-note-text" data-hero-note-text>原樣</p>', html)
        self.assertIn("展開全文", html)
        self.assertNotIn("data-hero-note-editable", html)
        self.assertIn("data-order-hero-note", hero(self.page(self.order(note="x"))))


class EditableHeroNoteScriptTests(SimpleTestCase):
    def test_script_proxies_to_the_order_form_and_reports_save_states(self):
        script = (Path(settings.BASE_DIR) / "static/js/order-hero-note.js").read_text(encoding="utf-8")
        for needle in ('"workspace-saved"', '"workspace-save-finished"', "儲存中…", "已儲存", "尚未儲存", 'new Event("input"', 'new Event("change"', "Escape"):
            self.assertIn(needle, script)
        styles = (Path(settings.BASE_DIR) / "static/css/order-workspace.css").read_text(encoding="utf-8")
        self.assertIn(".order-hero-note.is-empty", styles)
        self.assertIn('.order-hero-note[data-state="error"]', styles)
