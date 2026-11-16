"""T-190：證件裁切參數在辨識、草稿、建單、訂單頁之間的流向（合成圖，不含真實證件）。"""
import json
import shutil
import tempfile
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from sales.jobs import run_id_ocr_job
from sales.models import IdOcrJob, OrderDraft, OrderEvent, SalesOrder, SalesSource, VehicleColor, VehicleModel
from sales.services import id_card_crop, id_ocr
from sales.tests import id_card_synthetic as synthetic
from sales.tests.test_drafts import OrderDraftTests
from sales.tests.test_order_workspace import form_data, formset_data


FRONT_TEXT = "中華民國國民身分證\n姓名 林小華\n出生 民國79年1月1日\n性別 男\nA123456789"
BACK_TEXT = "父 林大山\n母 陳小美\n配偶\n役別\n出生地 台北市\n住址 台北市中山區\n0040750525"

SCENE_SIZE = (1600, 1200)


def scene_jpeg(side="front", **kwargs):
    return synthetic.jpeg_bytes(synthetic.scene(side, **kwargs))


def scene_upload(name="front.jpg", side="front", **kwargs):
    return SimpleUploadedFile(name, scene_jpeg(side, **kwargs), content_type="image/jpeg")


def manual_params(turn=0):
    return id_card_crop.params_from_pixels(synthetic.TILTED, turn, SCENE_SIZE, "manual")


class CardRecognitionTests(TestCase):
    """辨識改用裁切後的卡片：正常一次 OCR；看不出特徵時試 180° 並修正上緣；再不行退回整張四角度。"""

    def recognize(self, texts, image_bytes, crop=None):
        calls = []

        def fake(_client, image):
            calls.append(image.size)
            return texts[min(len(calls), len(texts)) - 1], ()

        with patch("sales.services.id_ocr._detect_text", side_effect=fake):
            result = id_ocr.recognize_side(image_bytes, "front", client=object(), crop=crop)
        return result, calls

    def test_auto_crop_recognizes_card_with_single_call(self):
        result, calls = self.recognize([FRONT_TEXT], scene_jpeg())
        self.assertEqual(calls, [(id_card_crop.CROP_WIDTH, id_card_crop.CROP_HEIGHT)])
        self.assertTrue(result.cropped)
        self.assertEqual(result.crop["mode"], "auto")
        self.assertEqual(result.crop["turn"], 0)
        self.assertFalse(result.crop["by_ocr"])

    def test_ocr_flips_turn_when_180_reads_better(self):
        result, calls = self.recognize(["看不清楚", FRONT_TEXT], scene_jpeg())
        self.assertEqual(len(calls), 2)
        self.assertEqual(result.angle, 180)
        self.assertEqual(result.crop["turn"], 2)
        self.assertTrue(result.crop["by_ocr"])

    def test_manual_crop_is_not_flipped_and_falls_back_to_whole_photo(self):
        result, calls = self.recognize(["看不清楚"], scene_jpeg(), crop=manual_params(turn=1))
        # 裁切後 1 次 + 整張四個角度 4 次；使用者指定的方向保留。
        self.assertEqual(len(calls), 5)
        self.assertFalse(result.cropped)
        self.assertEqual(result.crop["turn"], 1)
        self.assertEqual(result.crop["mode"], "manual")

    def test_manual_crop_for_other_photo_is_ignored(self):
        other = id_card_crop.params_from_pixels(synthetic.TILTED, 1, (1200, 1600), "manual")
        result, _calls = self.recognize([FRONT_TEXT], scene_jpeg(), crop=other)
        self.assertEqual(result.crop["mode"], "auto")

    def test_photo_without_card_uses_whole_photo_flow(self):
        image = synthetic.jpeg_bytes(synthetic.background((1200, 900)))
        result, calls = self.recognize([FRONT_TEXT], image)
        self.assertEqual(calls, [(1200, 900)])
        self.assertFalse(result.cropped)
        self.assertEqual(result.crop["mode"], "full")

    def test_recognize_id_card_returns_crop_for_both_sides(self):
        texts = iter([FRONT_TEXT, BACK_TEXT, ""])

        def fake(_client, _image):
            return next(texts, ""), ()

        with patch("sales.services.id_ocr._vision_client"), patch("sales.services.id_ocr._detect_text", side_effect=fake):
            result = id_ocr.recognize_id_card(scene_jpeg("front"), scene_jpeg("back"))
        self.assertEqual(result["fields"]["id_number"], "A123456789")
        self.assertEqual(result["crop"]["front"]["mode"], "auto")
        self.assertEqual(result["crop"]["back"]["mode"], "auto")
        self.assertEqual(result["rotation"], {"front": 0, "back": 0})


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="t190-media-"))
class CropEndpointTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        from django.conf import settings
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="crop-user", password="test-pass-123")
        self.client.force_login(self.user)

    def draft(self, owner=None):
        return OrderDraft.objects.create(
            owner_account=owner or self.user, created_by=(owner or self.user).username,
            id_front=ContentFile(scene_jpeg("front"), name="front.jpg"),
            id_back=ContentFile(scene_jpeg("back"), name="back.jpg"),
        )

    @patch("sales.views.django_rq.get_queue")
    def test_ocr_queue_receives_user_crop(self, get_queue):
        get_queue.return_value.count = 0
        params = json.dumps(manual_params())
        response = self.client.post(reverse("id_card_ocr"), {
            "front": scene_upload("front.jpg"), "back": scene_upload("back.jpg", "back"), "front_crop": params,
        })
        self.assertEqual(response.status_code, 202)
        args = get_queue.return_value.enqueue.call_args.args
        self.assertEqual(args[2], {"front": params})

    @patch("sales.views.django_rq.get_queue")
    def test_ocr_can_reuse_saved_draft_photos(self, get_queue):
        get_queue.return_value.count = 0
        draft = self.draft()
        response = self.client.post(reverse("id_card_ocr"), {"source": f"draft:{draft.pk}"})
        self.assertEqual(response.status_code, 202, response.content)
        job = IdOcrJob.objects.get()
        self.assertTrue(job.front and job.back)
        self.assertIsNone(get_queue.return_value.enqueue.call_args.args[2])

    @patch("sales.views.django_rq.get_queue")
    def test_ocr_source_outside_scope_is_rejected(self, get_queue):
        get_queue.return_value.count = 0
        other = get_user_model().objects.create_user(username="someone-else", password="test-pass-123")
        draft = self.draft(owner=other)
        with patch("sales.services.order_intake.scoped_drafts", return_value=OrderDraft.objects.none()):
            response = self.client.post(reverse("id_card_ocr"), {"source": f"draft:{draft.pk}"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(IdOcrJob.objects.exists())
        for bad in ("draft:not-a-uuid", "order:abc", "vehicle:1"):
            self.assertEqual(self.client.post(reverse("id_card_ocr"), {"source": bad}).status_code, 400)

    def test_worker_passes_crops_to_recognizer(self):
        job = IdOcrJob.objects.create(
            created_by=self.user, photo_token="t190",
            front=ContentFile(b"front", name="front.jpg"), back=ContentFile(b"back", name="back.jpg"),
        )
        with patch("sales.jobs.recognize_id_card", return_value={"fields": {}, "warnings": [], "rotation": {}}) as recognize:
            run_id_ocr_job(str(job.pk), {"front": "{}"})
        self.assertEqual(recognize.call_args.kwargs["crops"], {"front": "{}"})

    def test_detect_endpoint_with_upload_and_saved_photo(self):
        response = self.client.post(reverse("id_card_crop_detect"), {"side": "front", "image": scene_upload(upside_down=True)})
        self.assertEqual(response.status_code, 200, response.content)
        crop = response.json()["crop"]
        self.assertEqual((crop["mode"], crop["turn"], crop["src_w"], crop["src_h"]), ("auto", 2, 1600, 1200))

        draft = self.draft()
        response = self.client.post(reverse("id_card_crop_detect"), {"side": "back", "source": f"draft:{draft.pk}"})
        self.assertEqual(response.json()["crop"]["mode"], "auto")
        # 居留證：只轉成橫式，不依國民身分證版面翻轉。
        response = self.client.post(reverse("id_card_crop_detect"), {
            "side": "front", "document_type": "resident_certificate", "image": scene_upload(upside_down=True),
        })
        self.assertEqual(response.json()["crop"]["turn"], 0)

    def test_detect_endpoint_rejects_bad_requests(self):
        self.assertEqual(self.client.get(reverse("id_card_crop_detect")).status_code, 405)
        self.assertEqual(self.client.post(reverse("id_card_crop_detect"), {"side": "top"}).status_code, 400)
        self.assertEqual(self.client.post(reverse("id_card_crop_detect"), {"side": "front"}).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.post(reverse("id_card_crop_detect"), {"side": "front"}).status_code, 302)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="t190-media-"))
class DraftAndOrderCropTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        from django.conf import settings
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="crop-draft-user", password="test-pass-123")
        self.client.force_login(self.user)
        self.model = VehicleModel.objects.create(brand="測試", name="125", energy_type=VehicleModel.EnergyType.GAS)
        self.color = VehicleColor.objects.create(vehicle_model=self.model, name="白")

    def complete_data(self):
        return OrderDraftTests.complete_data(self)

    def save_draft(self, data):
        response = self.client.post(reverse("draft_save"), data)
        self.assertEqual(response.status_code, 200, response.content)
        return OrderDraft.objects.get(pk=response.json()["id"])

    def test_draft_stores_crop_outside_form_data_and_resets_on_new_photo(self):
        params = manual_params(turn=3)
        draft = self.save_draft({
            "owner_name": "測試車主", "id_front": scene_upload(), "id_front_crop": json.dumps(params),
        })
        self.assertEqual(draft.id_front_crop, params)
        self.assertNotIn("id_front_crop", draft.data)

        # 沒換照片時：空白或屬於別張照片的參數不覆蓋。
        stale = id_card_crop.params_from_pixels(synthetic.TILTED, 0, (800, 600), "manual")
        draft = self.save_draft({"_draft_id": draft.pk, "_draft_revision": draft.revision, "owner_name": "測試車主",
                                 "id_front_crop": json.dumps(stale)})
        self.assertEqual(draft.id_front_crop, params)
        draft = self.save_draft({"_draft_id": draft.pk, "_draft_revision": draft.revision, "owner_name": "測試車主",
                                 "id_front_crop": json.dumps(manual_params(turn=1))})
        self.assertEqual(draft.id_front_crop["turn"], 1)

        # 換照片沒帶參數：舊參數作廢。
        draft = self.save_draft({"_draft_id": draft.pk, "_draft_revision": draft.revision, "owner_name": "測試車主",
                                 "id_front": scene_upload("again.jpg")})
        self.assertIsNone(draft.id_front_crop)

        draft.id_front_crop = params
        draft.save(update_fields=["id_front_crop"])
        draft = self.save_draft({"_draft_id": draft.pk, "_draft_revision": draft.revision, "owner_name": "測試車主",
                                 "_remove_id_front": "1"})
        self.assertFalse(draft.id_front)
        self.assertIsNone(draft.id_front_crop)

    def test_order_created_from_draft_keeps_draft_crop(self):
        params = manual_params(turn=2)
        draft = OrderDraft.objects.create(
            data=self.complete_data(), created_by=self.user.username, updated_by=self.user.username,
            id_front=ContentFile(scene_jpeg("front"), name="front.jpg"),
            id_back=ContentFile(scene_jpeg("back"), name="back.jpg"),
            id_front_crop=params,
        )
        post_data = {**self.complete_data(), "_draft_id": str(draft.pk), "_draft_revision": str(draft.revision)}
        back_params = id_card_crop.params_from_pixels(synthetic.TILTED, 0, SCENE_SIZE, "manual")
        post_data["id_back_crop"] = json.dumps(back_params)
        response = self.client.post(reverse("order_create"), post_data)
        self.assertEqual(response.status_code, 302)
        order = SalesOrder.objects.get(owner_name="測試車主")
        self.assertEqual(order.id_front_crop, params)
        self.assertEqual(order.id_back_crop, back_params)

    def test_create_form_shows_saved_crop_for_editor(self):
        draft = OrderDraft.objects.create(
            data=self.complete_data(), created_by=self.user.username,
            id_front=ContentFile(scene_jpeg("front"), name="front.jpg"), id_front_crop=manual_params(turn=1),
        )
        response = self.client.get(reverse("order_create"), {"draft": draft.pk})
        self.assertContains(response, 'name="id_front_crop"')
        self.assertContains(response, "&quot;turn&quot;: 1")
        self.assertContains(response, 'data-id-crop-editor')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="t190-media-"))
class OrderPageCropTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        from django.conf import settings
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("crop-admin", password="test-pass-123")
        self.client.force_login(self.admin)
        model = VehicleModel.objects.create(brand="QA", name="裁切車型", energy_type="gas")
        color = VehicleColor.objects.create(vehicle_model=model, name="白")
        source = SalesSource.objects.create(name="馭盛", source_type="store")
        self.order = SalesOrder.objects.create(
            source_type="store", source=source, order_date=date(2026, 11, 16), owner_type="local",
            owner_name="測試車主", owner_id_number="A123456789", owner_phone="0912345678", owner_address="測試地址",
            vehicle_model=model, color=color, vehicle_price=70000, actual_balance=70000, calculated_balance=70000,
            payment_type="cash", delivery_method="store_pickup",
            id_front=ContentFile(scene_jpeg("front"), name="front.jpg"),
            id_back=ContentFile(scene_jpeg("back"), name="back.jpg"),
        )
        from sales.services.print_company import initialize_company
        initialize_company(self.order, self.admin)
        self.order.save(update_fields=["print_company", "print_company_snapshot"])

    def workspace_data(self):
        response = self.client.get(reverse("order_detail", args=[self.order.pk]), {"tab": "order"})
        self.order.refresh_from_db()
        return {**form_data(response.context["form"]), **formset_data(response.context["formset"]),
                **formset_data(response.context["fee_formset"]), "_order_revision": self.order.revision, "_workspace": "1"}

    def test_order_page_saves_crop_with_event_and_without_change_noise(self):
        data = self.workspace_data()
        data["id_front_crop"] = json.dumps(manual_params(turn=1))
        response = self.client.post(reverse("order_edit", args=[self.order.pk]), data, HTTP_X_ORDER_WORKSPACE="1")
        self.assertEqual(response.status_code, 200, response.content)
        self.order.refresh_from_db()
        self.assertEqual(self.order.id_front_crop["turn"], 1)
        event = OrderEvent.objects.get(order=self.order, event_type="id_crop_adjusted")
        self.assertIn("正面", event.description)
        change = self.order.changes.order_by("-pk").first()
        self.assertNotIn("證件正面裁切", json.dumps(change.changes, ensure_ascii=False))

        # 再存一次同樣的參數：不重複記處理紀錄。
        data = self.workspace_data()
        data["id_front_crop"] = json.dumps(manual_params(turn=1))
        self.client.post(reverse("order_edit", args=[self.order.pk]), data, HTTP_X_ORDER_WORKSPACE="1")
        self.assertEqual(OrderEvent.objects.filter(order=self.order, event_type="id_crop_adjusted").count(), 1)

    def test_deleting_photo_clears_crop(self):
        self.order.id_back_crop = manual_params()
        self.order.save(update_fields=["id_back_crop"])
        response = self.client.post(reverse("order_file_delete", args=[self.order.pk, "id_back"]))
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertFalse(self.order.id_back)
        self.assertIsNone(self.order.id_back_crop)
