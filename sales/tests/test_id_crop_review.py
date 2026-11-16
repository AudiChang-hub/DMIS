"""T-199：訂單頁附件、訂單明細改顯示裁切後的卡片；T-200：沒把握時標「建議確認裁切」。合成證件圖，不含真實證件。"""
import io
import json
import shutil
import tempfile
import zipfile
from datetime import date
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from sales.access.models import UserAccessState
from sales.models import SalesOrder, SalesSource, VehicleColor, VehicleModel
from sales.services import form_print, id_card_crop, id_ocr
from sales.tests import id_card_synthetic as synthetic

PERSPECTIVE = [[500, 250], [1100, 300], [1350, 950], [200, 900]]
SMALL = [[700, 550], [900, 560], [895, 690], [695, 680]]


def jpeg(side="front", **kwargs):
    return synthetic.jpeg_bytes(synthetic.scene(side, **kwargs))


def blank_card_scene():
    card = synthetic.card("front")
    card[:] = 228
    return synthetic.paste(synthetic.background(), card, synthetic.TILTED)


class ReviewSignalTests(SimpleTestCase):
    """每個低信心訊號單獨觸發，正常卡片不標。"""

    def params(self, array, side="front"):
        return id_card_crop.auto_params(synthetic.to_pil(array), side)

    def test_normal_cards_are_not_flagged(self):
        for side in ("front", "back"):
            for upside_down in (False, True):
                with self.subTest(side=side, upside_down=upside_down):
                    self.assertFalse(self.params(synthetic.scene(side, upside_down=upside_down), side)["needs_review"])
        sleeve = [[240, 200], [1310, 250], [1280, 930], [220, 870]]
        self.assertFalse(self.params(synthetic.scene("front", sleeve=sleeve))["needs_review"])

    def test_no_card_found_is_flagged(self):
        params = self.params(synthetic.background((1200, 900)))
        self.assertEqual(params["mode"], "full")
        self.assertTrue(params["needs_review"])

    def test_aspect_far_from_id_card_is_flagged(self):
        self.assertTrue(self.params(synthetic.scene("front", PERSPECTIVE))["needs_review"])

    def test_tiny_card_is_flagged(self):
        self.assertTrue(self.params(synthetic.scene("front", SMALL))["needs_review"])

    def test_unclear_orientation_is_flagged_only_for_national_id(self):
        self.assertTrue(self.params(blank_card_scene(), "front")["needs_review"])
        self.assertTrue(self.params(blank_card_scene(), "back")["needs_review"])
        # 居留證不依版面判斷上下，就不因方向而提醒。
        self.assertFalse(self.params(blank_card_scene(), None)["needs_review"])

    def test_manual_or_applied_params_never_flagged(self):
        params = {**id_card_crop.params_from_pixels(synthetic.TILTED, 0, (1600, 1200), "auto"), "needs_review": True}
        self.assertTrue(id_card_crop.clean_params(params, (1600, 1200))["needs_review"])
        self.assertFalse(id_card_crop.clean_params({**params, "mode": "manual"}, (1600, 1200))["needs_review"])
        self.assertFalse(id_card_crop.clean_params({**params, "needs_review": False}, (1600, 1200))["needs_review"])


class OcrReviewTests(SimpleTestCase):
    FRONT = "中華民國國民身分證\n姓名 林小華\n出生 民國79年1月1日\n性別 男\nA123456789"

    def recognize(self, texts, image_bytes, crop=None):
        answers = iter(texts)
        with patch("sales.services.id_ocr._detect_text", side_effect=lambda _c, _i: (next(answers, ""), ())):
            return id_ocr.recognize_side(image_bytes, "front", client=object(), crop=crop)

    def test_strong_ocr_on_card_clears_review(self):
        flagged = {**id_card_crop.auto_params(synthetic.to_pil(synthetic.scene("front", PERSPECTIVE)), "front")}
        self.assertTrue(flagged["needs_review"])
        result = self.recognize([self.FRONT], jpeg("front", corners=PERSPECTIVE), crop=flagged)
        self.assertTrue(result.cropped)
        self.assertFalse(result.crop["needs_review"])

    def test_fallback_to_whole_photo_flags_review(self):
        result = self.recognize(["看不清楚"] * 6, jpeg("front"))
        self.assertFalse(result.cropped)
        self.assertTrue(result.crop["needs_review"])

    def test_fallback_keeps_manual_unflagged(self):
        manual = id_card_crop.params_from_pixels(synthetic.TILTED, 0, (1600, 1200), "manual")
        result = self.recognize(["看不清楚"] * 6, jpeg("front"), crop=manual)
        self.assertFalse(result.crop["needs_review"])

    def test_ocr_turn_correction_alone_is_not_flagged(self):
        result = self.recognize(["看不清楚", self.FRONT], jpeg("front"))
        self.assertTrue(result.crop["by_ocr"])
        self.assertFalse(result.crop["needs_review"])


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="t199-media-"))
class OrderCardViewTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        cache.clear()
        self.admin = get_user_model().objects.create_superuser("t199-admin", password="test-pass-123")
        self.client.force_login(self.admin)
        model = VehicleModel.objects.create(brand="QA", name="卡片車型", energy_type="gas")
        color = VehicleColor.objects.create(vehicle_model=model, name="白")
        source = SalesSource.objects.create(name="馭盛", source_type="store")
        self.order = SalesOrder.objects.create(
            source_type="store", source=source, order_date=date(2026, 11, 16), owner_type="local",
            owner_name="測試車主", owner_id_number="A123456789", owner_phone="0912345678", owner_address="測試地址",
            vehicle_model=model, color=color, vehicle_price=70000, actual_balance=70000, calculated_balance=70000,
            payment_type="cash", delivery_method="store_pickup", status=SalesOrder.Status.ALLOCATION_PENDING,
            id_front=ContentFile(jpeg("front", upside_down=True), name="front.jpg"),
        )

    def card(self, field="id_front", client=None):
        return (client or self.client).get(reverse("protected_media", args=["order", self.order.pk, field]), {"card": "1"})

    def card_image(self, response):
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertIn("no-store", response["Cache-Control"])
        return Image.open(io.BytesIO(response.content))

    def test_card_without_saved_params_is_detected_and_not_written(self):
        image = self.card_image(self.card())
        self.assertEqual(image.size, (id_card_crop.CROP_WIDTH, id_card_crop.CROP_HEIGHT))
        self.assertGreater(id_card_crop.front_upright_score(__import__("numpy").asarray(image)), 0)  # 倒拍已轉正
        self.order.refresh_from_db()
        self.assertIsNone(self.order.id_front_crop)

    def test_card_uses_saved_params(self):
        manual = id_card_crop.params_from_pixels(synthetic.TILTED, 0, (1600, 1200), "manual")
        self.order.id_front_crop = manual
        self.order.save(update_fields=["id_front_crop"])
        image = self.card_image(self.card())
        # 存的是 turn 0（使用者決定不轉），卡片保持倒著。
        self.assertLess(id_card_crop.front_upright_score(__import__("numpy").asarray(image)), 0)

    def test_only_one_side_and_missing_side(self):
        self.card_image(self.card("id_front"))
        self.assertEqual(self.card("id_back").status_code, 404)

    def test_resident_certificate_only_turns_to_landscape(self):
        self.order.owner_type = SalesOrder.OwnerType.FOREIGN
        self.order.save(update_fields=["owner_type"])
        image = self.card_image(self.card())
        self.assertLess(id_card_crop.front_upright_score(__import__("numpy").asarray(image)), 0)

    def test_without_permission_no_card(self):
        self.client.logout()
        self.assertEqual(self.card().status_code, 302)
        clerk = get_user_model().objects.create_user("t199-clerk", password="test-pass-123")
        UserAccessState.objects.create(user=clerk, configured=True)
        self.client.force_login(clerk)
        response = self.card()
        self.assertIn(response.status_code, {302, 403, 404})
        self.assertNotEqual(response.get("Content-Type"), "image/jpeg")

    def test_card_param_ignored_for_other_files(self):
        self.order.refund_proof = ContentFile(b"%PDF-1.4\n", name="refund.pdf")
        self.order.save(update_fields=["refund_proof"])
        response = self.client.get(reverse("protected_media", args=["order", self.order.pk, "refund_proof"]), {"card": "1"})
        self.assertNotEqual(response.get("Content-Type"), "image/jpeg")

    def test_attachments_panel_and_detail_show_card_with_original_link(self):
        self.order.id_back = ContentFile(synthetic.jpeg_bytes(synthetic.background((1200, 900))), name="back.png")
        self.order.save(update_fields=["id_back"])
        page = self.client.get(reverse("order_detail", args=[self.order.pk]), {"tab": "attachments"}).content.decode()
        original = reverse("protected_media", args=["order", self.order.pk, "id_front"])
        self.assertIn(f'href="{original}?card=1&amp;c=', page)
        self.assertIn(f'<a href="{original}" target="_blank" rel="noopener">查看原圖</a>', page)
        # 反面找不到卡片 → 建議確認裁切；正面正常 → 不標。
        self.assertEqual(page.count('<span class="id-card-review">建議確認裁切</span>'), 1)
        # 不能編輯的訂單（例如已取消）在「訂車與配件」顯示唯讀車主資料：同樣是卡片＋查看原圖＋提醒。
        SalesOrder.objects.filter(pk=self.order.pk).update(status=SalesOrder.Status.CANCELLED)
        detail = self.client.get(reverse("order_detail", args=[self.order.pk]), {"tab": "order"}).content.decode()
        self.assertIn('<div class="id-card-link">', detail)
        self.assertIn(f'href="{original}?card=1&amp;c=', detail)
        # 同一頁也含附件面板：唯讀區與附件面板各一次。
        self.assertEqual(detail.count('<span class="id-card-review">建議確認裁切</span>'), 2)
        # 全部下載 ZIP 仍放原圖，副檔名跟原圖。
        data = b"".join(self.client.get(reverse("order_attachments_zip", args=[self.order.pk])).streaming_content)
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        self.assertIn("車主證件/證件正面.jpg", names)
        self.assertIn("車主證件/證件反面.png", names)

    def test_review_state_consistent_across_card_view_and_print(self):
        self.order.id_back = ContentFile(synthetic.jpeg_bytes(synthetic.background((1200, 900))), name="back.jpg")
        self.order.save(update_fields=["id_back"])
        views = {field: id_card_crop.card_view(self.order, "order", field) for field in ("id_front", "id_back")}
        job = form_print.PrintJob(self.order, "id_copy")
        form_print.build_forms_pdf([job])
        slots = {slot["field"]: slot for slot in job.id_slots}
        for field in ("id_front", "id_back"):
            self.assertEqual(views[field]["needs_review"], slots[field]["crop"]["needs_review"])
        self.assertEqual((views["id_front"]["needs_review"], views["id_back"]["needs_review"]), (False, True))
        preview = self.client.post(reverse("form_print_preview"), {"job": [f"{self.order.pk}:id_copy"]}).content.decode()
        self.assertEqual(preview.count("print-preview__id-review"), 1)

    def test_applying_in_print_preview_clears_review(self):
        flagged = {**id_card_crop.params_from_pixels(synthetic.TILTED, 2, (1600, 1200), "auto"), "needs_review": True}
        self.order.id_front_crop = flagged
        self.order.save(update_fields=["id_front_crop"])
        self.assertTrue(id_card_crop.card_view(self.order, "order", "id_front")["needs_review"])
        applied = {**flagged, "mode": "manual", "needs_review": False}
        self.client.post(reverse("form_print_id_crop", args=[self.order.pk]), {"side": "front", "crop": json.dumps(applied)})
        self.order.refresh_from_db()
        self.assertFalse(id_card_crop.card_view(self.order, "order", "id_front")["needs_review"])
