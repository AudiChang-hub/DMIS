import base64
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from sales.services.id_ocr import extract_fields, validate_taiwan_id


ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAusB9Y9Zl1sAAAAASUVORK5CYII="
)


class IdFieldExtractionTests(TestCase):
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

    def test_extracts_multiline_address(self):
        text = "住址\n台北市中山區中山里1鄰\n中山北路一段1號3樓\n出生地台灣"

        result = extract_fields(text, "back")

        self.assertEqual(
            result["address"], "台北市中山區中山里1鄰中山北路一段1號3樓"
        )

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

    @patch("sales.views.recognize_id_card")
    def test_returns_structured_ocr_result(self, recognize):
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

        response = self.client.post(
            reverse("id_card_ocr"),
            {"front": self.image("front.png"), "back": self.image("back.png")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["fields"]["name"], "王小明")

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
