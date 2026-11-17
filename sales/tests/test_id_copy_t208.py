"""T-208（2.20.0）：身分證影本照排版工具——備註排版、預設備註（不保存）、單張訂單影本頁與入口（合成證件圖）。"""
import html
import json
import shutil
import tempfile
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from sales.models import OrderEvent, SalesSource, UserAccessState
from sales.services import form_print, id_copy_note
from sales.tests import test_order_lifecycle as lifecycle
from sales.tests.test_form_print_id_copy import pdf_text, photo

NOTE_W, NOTE_H = form_print.id_note_rect(0)[2:]


def layout(text):
    return id_copy_note.layout_note(text, NOTE_W, NOTE_H, form_print.SANS)


class IdCopyNoteLayoutTests(SimpleTestCase):
    def test_note_box_matches_the_layout_tool(self):
        self.assertAlmostEqual(NOTE_W, 210 - 5 - (5 + 82.7 * 2 + 3) - 3, places=3)  # ≈ 28.6 mm
        self.assertAlmostEqual(NOTE_H, 82.7 * 54 / 85.6, places=3)

    def test_short_note_uses_16pt(self):
        result = layout("好車機車行")
        self.assertAlmostEqual(result.font_size, id_copy_note.NOTE_MAX_FONT)
        self.assertEqual(result.lines, ("好車機車行",))
        self.assertFalse(result.truncated)

    def test_long_note_shrinks_but_not_below_12pt(self):
        result = layout("請於週一至週五上午九點到十二點之間聯絡車主確認交車時間與地點並提醒攜帶印章與行照，交車前一天再電話確認")
        self.assertLess(result.font_size, id_copy_note.NOTE_MAX_FONT)
        self.assertGreaterEqual(result.font_size, id_copy_note.NOTE_MIN_FONT - 1e-9)
        self.assertFalse(result.truncated)
        self.assertLessEqual(len(result.lines) * result.line_height, NOTE_H + 0.01)

    def test_too_long_note_is_cut_with_ellipsis_at_12pt(self):
        result = layout("備註" * 80)
        self.assertTrue(result.truncated)
        self.assertAlmostEqual(result.font_size, id_copy_note.NOTE_MIN_FONT)
        self.assertTrue(result.lines[-1].endswith("…"))
        self.assertLessEqual(len(result.lines) * result.line_height, NOTE_H + 0.01)

    def test_phone_splits_after_hyphen_and_full_width_becomes_half_width(self):
        result = layout("０９１２－３４５－６７８")
        self.assertEqual("".join(result.lines), "0912-345-678")
        if len(result.lines) > 1:
            self.assertTrue(result.lines[0].endswith("-"))

    def test_line_breaking_keeps_closing_punctuation_off_line_start(self):
        for line in layout("車主電話（請先確認），交車前一天再打一次。謝謝。").lines:
            self.assertFalse(line[:1] in id_copy_note.NO_LINE_START, line)

    def test_blank_note_draws_nothing(self):
        self.assertEqual(layout("  \n ").lines, ())


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="t208-idcopy-"))
class IdCopyNoteAndPageTests(TestCase):
    make_order = lifecycle.OrderLifecycleTests.make_order

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        lifecycle.OrderLifecycleTests.setUp(self)
        self.order, _vehicle = self.make_order(deposit=Decimal("5000"))
        self.order.id_front = photo("front")
        self.order.id_back = photo("back", upside_down=True)
        self.order.save(update_fields=["id_front", "id_back"])
        self.client.force_login(self.user)

    def test_default_note_store_is_phone_dealer_and_platform_add_name(self):
        self.assertEqual(form_print.default_id_copy_note(self.order), "0912345678")
        dealer_order, _vehicle = self.make_order(dealer=True)
        self.assertEqual(form_print.default_id_copy_note(dealer_order), f"{self.source.name}\n0912345678")
        platform = SalesSource.objects.create(name="網路平台甲", source_type=SalesSource.SourceType.PLATFORM)
        dealer_order.source = platform
        self.assertEqual(form_print.default_id_copy_note(dealer_order), "網路平台甲\n0912345678")
        dealer_order.owner_phone = ""
        self.assertEqual(form_print.default_id_copy_note(dealer_order), "網路平台甲")

    def test_posted_note_is_printed_and_not_saved(self):
        revision = self.order.revision
        data = {"job": [f"{self.order.pk}:id_copy"], f"idnote_{self.order.pk}": "測試車行\n0987-654-321"}
        preview = self.client.post(reverse("form_print_preview"), data).content.decode()
        jobs = json.loads(html.unescape(preview.split('data-id-jobs="', 1)[1].split('"', 1)[0]))
        self.assertEqual(jobs, [{"order": self.order.pk, "note": "測試車行\n0987-654-321"}])
        printed = b"".join(self.client.post(reverse("form_print_pdf"), data).streaming_content)
        self.assertIn("測試車行", pdf_text(printed))
        self.order.refresh_from_db()
        self.assertEqual(self.order.revision, revision)
        event = OrderEvent.objects.get(order=self.order, event_type="identity_copy_printed")
        self.assertNotIn("測試車行", event.description)
        self.assertIn("每頁 5 組", event.description)

    def test_missing_note_field_uses_default_and_note_is_capped(self):
        data = {"job": [f"{self.order.pk}:id_copy"]}
        printed = pdf_text(b"".join(self.client.post(reverse("form_print_pdf"), data).streaming_content))
        # 16 pt 一行放不下時在第 4 碼後換行，文字擷取會帶換行。
        self.assertIn("0912345678", "".join(printed.split()))
        found = [(self.order, "id_copy")]
        request = self.client.post(reverse("form_print_preview"), data).wsgi_request
        request.POST = request.POST.copy()
        request.POST[f"idnote_{self.order.pk}"] = "字" * 200
        from sales.form_print_views import _print_jobs
        self.assertEqual(len(_print_jobs(request, found)[0].id_note), id_copy_note.NOTE_MAX_CHARS)

    def test_print_list_offers_note_and_warns_missing_side(self):
        self.order.id_back = ""
        self.order.save(update_fields=["id_back"])
        content = self.client.get(reverse("form_print"), {"tab": "all"}).content.decode()
        self.assertIn('data-id-note="0912345678"', content)
        self.assertIn("data-item-id-note", content)
        self.assertIn("缺：反面照片", content)

    def test_order_page_has_entry_and_single_page_previews_with_note(self):
        detail = self.client.get(reverse("order_detail", args=[self.order.pk])).content.decode()
        url = reverse("order_id_copy", args=[self.order.pk])
        self.assertIn(f'href="{url}"', detail)
        self.assertIn("列印身分證影本", detail)

        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, f'name="idnote_{self.order.pk}"')
        self.assertContains(page, ">0912345678</textarea>")
        self.assertContains(page, f'value="{self.order.pk}:id_copy"')
        self.assertContains(page, f'data-preview-url="{reverse("form_print_preview")}"')
        self.assertContains(page, f'action="{reverse("form_print_pdf")}"')
        self.assertContains(page, "js/order-id-copy.js")
        self.assertContains(page, "js/form-print-id-copy.js")
        self.assertContains(page, "82.7 × 52.2 mm")
        self.assertNotContains(page, "實際尺寸")

    def test_single_page_not_for_orders_without_photos_or_people(self):
        other, _vehicle = self.make_order()
        self.assertEqual(self.client.get(reverse("order_id_copy", args=[other.pk])).status_code, 404)
        self.assertNotIn(reverse("order_id_copy", args=[other.pk]),
                         self.client.get(reverse("order_detail", args=[other.pk])).content.decode())

    def test_single_page_requires_permission(self):
        url = reverse("order_id_copy", args=[self.order.pk])
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        clerk = get_user_model().objects.create_user("t208-clerk", password="test-pass-123")
        UserAccessState.objects.create(user=clerk, configured=True)
        self.client.force_login(clerk)
        response = self.client.get(url)
        self.assertIn(response.status_code, {302, 403, 404})
        self.assertNotIn(b"idnote_", response.content)
