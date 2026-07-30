import base64
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from sales.jobs import run_id_ocr_job
from sales.models import IdOcrJob
from sales.services.id_ocr import (
    _clean_name_text,
    _choose_name_candidate,
    _extract_birth_date,
    _extract_id_number,
    extract_fields,
    validate_taiwan_id,
)


ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAusB9Y9Zl1sAAAAASUVORK5CYII="
)


class IdFieldExtractionTests(TestCase):
    def test_cleans_name_region_with_layout_labels(self):
        self.assertEqual(
            _clean_name_text("姓名\n張鴻\n性別 男\n賢\n出生 民國"),
            "張鴻賢",
        )

    def test_name_region_only_completes_one_missing_character(self):
        self.assertEqual(_choose_name_candidate("林小", "林小華"), "林小華")
        self.assertEqual(_choose_name_candidate("林小華", "林小華脂"), "林小華")
        self.assertEqual(_choose_name_candidate("", "林小華"), "林小華")

    def test_extracts_vertical_name_character_after_gender_label(self):
        text = "姓名 張鴻\n性別 男\n賢\n出生 民國70年1月2日"

        result = extract_fields(text, "front")

        self.assertEqual(result["name"], "張鴻賢")

    def test_extracts_front_fields_and_converts_roc_date(self):
        text = (
            "中華民國國民身分證\n"
            "姓名 王小明\n"
            "出生 民國080年03月15日\n"
            "身分證統一編號 A123456789\n"
        )

        result = extract_fields(text, "front")

        self.assertEqual(result["name"], "王小明")
        self.assertEqual(result["birth_date"], "1991-03-15")
        self.assertEqual(result["id_number"], "A123456789")
        self.assertTrue(result["id_number_valid"])

    def test_birth_field_wins_over_later_issue_date(self):
        text = (
            "姓名 林小華\n"
            "出生年月日 民國77年2月23日\n"
            "發證日期 民國115年4月16日換發"
        )

        self.assertEqual(_extract_birth_date(text), "1988-02-23")

    def test_id_number_repairs_common_ocr_digit_confusion_with_checksum(self):
        self.assertEqual(_extract_id_number("統一編號 A1234567B9"), "A123456789")

    def test_extracts_spaced_name_and_id_number(self):
        text = (
            "中華民國國民身分證\n姓名 張　小　華\n"
            "出生年月日 民國 77 年 2 月 23 日\n"
            "統一編號 A 1 2 3 4 5 6 7 8 9"
        )

        result = extract_fields(text, "front")

        self.assertEqual(result["name"], "張小華")
        self.assertEqual(result["birth_date"], "1988-02-23")
        self.assertEqual(result["id_number"], "A123456789")

    def test_extracts_multiline_address(self):
        text = "住址\n台北市中山區中山里1鄰\n中山北路一段1號3樓\n出生地台灣"

        result = extract_fields(text, "back")

        self.assertEqual(
            result["address"], "台北市中山區中山里1鄰中山北路一段1號3樓"
        )

    def test_extracts_address_when_label_has_spacing(self):
        text = "父 林大山\n住 址 台北市萬華區忠德里7鄰\n寶興街115號\n"

        result = extract_fields(text, "back")

        self.assertEqual(result["address"], "台北市萬華區忠德里7鄰寶興街115號")

    def test_taiwan_id_checksum(self):
        self.assertTrue(validate_taiwan_id("A123456789"))
        self.assertFalse(validate_taiwan_id("A123456788"))
        self.assertFalse(validate_taiwan_id("NOT-AN-ID"))


class IdOcrEndpointTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="ocr-user", password="test-pass-123"
        )

    def image(self, name):
        return SimpleUploadedFile(name, ONE_PIXEL_PNG, content_type="image/png")

    def test_requires_login(self):
        response = self.client.post(
            reverse("id_card_ocr"),
            {"front": self.image("front.png"), "back": self.image("back.png")},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    @patch("sales.views.django_rq.get_queue")
    def test_queues_ocr_without_waiting_for_result(self, get_queue):
        queue = get_queue.return_value
        queue.count = 0
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("id_card_ocr"),
            {"front": self.image("front.png"), "back": self.image("back.png")},
        )

        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.json()["ok"])
        self.assertTrue(response.json()["job_id"])
        queue.enqueue.assert_called_once()

    @patch("sales.jobs.recognize_id_card")
    def test_worker_persists_result_and_status_endpoint_returns_it(self, recognize):
        recognize.return_value = {
            "fields": {
                "name": "王小明",
                "birth_date": "1991-03-15",
                "id_number": "A123456789",
                "id_number_valid": True,
                "address": "台北市中山區",
            },
            "warnings": [],
            "rotation": {"front": 0, "back": 90},
        }
        self.client.force_login(self.user)
        job = IdOcrJob.objects.create(
            created_by=self.user,
            front=self.image("front.png"),
            back=self.image("back.png"),
            photo_token="photo-v1",
        )
        front_name = job.front.name
        back_name = job.back.name
        run_id_ocr_job(str(job.pk))

        response = self.client.get(reverse("id_card_ocr_status", args=[job.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["status"], IdOcrJob.Status.SUCCEEDED)
        self.assertEqual(response.json()["fields"]["name"], "王小明")
        self.assertFalse(job.front.storage.exists(front_name))
        self.assertFalse(job.back.storage.exists(back_name))

    def test_rejects_non_image_uploads(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("id_card_ocr"),
            {
                "front": SimpleUploadedFile(
                    "front.txt", b"not image", content_type="text/plain"
                ),
                "back": self.image("back.png"),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
