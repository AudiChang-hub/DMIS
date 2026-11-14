"""T-175（使用者 2026-11-13 回饋第 7 頁）：建立訂單時的備註以便條紙顯示在訂單頁首。

備註＝建立訂單「訂金」步驟的 SalesOrder.note；沒有備註不顯示空便條，長備註截斷可展開，訂單頁改了備註頁首跟著換新。
"""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from sales.services.order_wizard import STEP_FIELDS
from sales.tests import test_completed_order_corrections as correction_tests

WORKSPACE = {"HTTP_X_ORDER_WORKSPACE": "1", "HTTP_ACCEPT": "application/json"}


def hero(page):
    start = page.index("data-order-hero")
    return page[start:page.index("</section>", start)]


class HeroNoteTests(TestCase):
    setUpTestData = classmethod(correction_tests.CompletedOrderCorrectionTests.setUpTestData.__func__)
    setUp = correction_tests.CompletedOrderCorrectionTests.setUp
    order = correction_tests.CompletedOrderCorrectionTests.order
    payload = correction_tests.CompletedOrderCorrectionTests.payload

    def page(self, order):
        return self.client.get(reverse("order_detail", args=[order.pk])).content.decode()

    def test_wizard_note_is_the_order_note(self):
        self.assertIn("note", STEP_FIELDS["deposit"])

    def test_note_shows_as_sticky_note_next_to_title(self):
        order = self.order(note="客人週六下午來牽車\n記得裝手機架")
        header = hero(self.page(order))
        title = header.split('class="title-with-status"', 1)[1].split("</div>", 1)[0]
        self.assertIn("data-order-hero-note", title)
        self.assertLess(title.index("data-save-chip"), title.index("data-order-hero-note"))
        note = title.split("data-order-hero-note", 1)[1].split("</aside>", 1)[0]
        self.assertNotIn(" hidden", note.split(">", 1)[0])
        self.assertIn("客人週六下午來牽車\n記得裝手機架", note)
        self.assertIn('aria-expanded="false"', note)
        self.assertIn("展開全文", note)

    def test_no_note_renders_no_empty_sticky(self):
        header = hero(self.page(self.order(note="")))
        note = header.split("data-order-hero-note", 1)[1].split("</aside>", 1)[0]
        self.assertIn(" hidden", note.split(">", 1)[0])
        self.assertNotIn("data-hero-note-text", note)
        self.assertNotIn("備註", note.split(">", 1)[1])

    def test_note_is_escaped(self):
        header = hero(self.page(self.order(note="<script>alert(1)</script>")))
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", header)
        self.assertNotIn("<script>alert(1)", header)

    def test_autosave_returns_fresh_sticky_note(self):
        order = self.order(note="")
        response = self.client.post(reverse("order_edit", args=[order.pk]),
                                    self.payload(order, note="改成週日交車"), **WORKSPACE)
        self.assertEqual(response.status_code, 200, response.content[:500])
        payload = response.json()
        self.assertTrue(payload["ok"], payload)
        self.assertIn("改成週日交車", payload["hero_note_html"])
        self.assertNotIn(" hidden", payload["hero_note_html"].split(">", 1)[0])

        order.refresh_from_db()
        response = self.client.post(reverse("order_edit", args=[order.pk]),
                                    self.payload(order, note=""), **WORKSPACE)
        self.assertTrue(response.json()["ok"], response.json())
        html = response.json()["hero_note_html"]
        self.assertIn(" hidden", html.split(">", 1)[0])
        self.assertNotIn("改成週日交車", html)


class HeroNoteAssetTests(SimpleTestCase):
    def test_long_note_clamps_and_mobile_takes_full_width(self):
        base = Path(settings.BASE_DIR)
        styles = (base / "static/css/order-workspace.css").read_text(encoding="utf-8")
        text = styles.split(".order-hero-note__text {", 1)[1].split("}", 1)[0]
        self.assertIn("-webkit-line-clamp: 3", text)
        self.assertIn("overflow-wrap: anywhere", text)
        mobile = styles.split("@media (max-width: 860px) {\n  .order-hero-note {", 1)[1].split("}", 1)[0]
        self.assertIn("flex-basis: 100%", mobile)
        self.assertIn("transform: none", mobile)
        script = (base / "static/js/order-hero-note.js").read_text(encoding="utf-8")
        self.assertIn("hero_note_html", script)
        self.assertIn('addEventListener("workspace-saved"', script)
        template = (base / "templates/sales/order_detail.html").read_text(encoding="utf-8")
        self.assertIn("js/order-hero-note.js", template)
