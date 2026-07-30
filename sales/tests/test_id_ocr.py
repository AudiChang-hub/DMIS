import base64
from types import SimpleNamespace
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
    _extract_resident_name_from_layout,
    _resident_side_scores,
    _side_scores,
    detect_id_side,
    detect_resident_certificate_side,
    extract_fields,
    extract_resident_certificate_fields,
    IdOcrError,
    recognize_id_card,
    validate_taiwan_id,
)


ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAusB9Y9Zl1sAAAAASUVORK5CYII="
)


class IdFieldExtractionTests(TestCase):
    def test_detects_front_from_title_and_identity_fields(self):
        text = (
            "中華民國國民身分證\n姓名 林小華\n"
            "出生年月日 民國77年2月23日\nA123456789"
        )

        self.assertEqual(detect_id_side(text), "front")
        self.assertGreater(_side_scores(text)["front"], _side_scores(text)["back"])

    def test_detects_front_when_vision_reads_shenfen_as_identity_variant(self):
        self.assertEqual(detect_id_side("中華民國國民身份證"), "front")

    def test_detects_back_from_serial_and_address_fields(self):
        text = "父 林大山\n母 陳小美\n出生地 台北市\n住址 台北市中山區\n0040750525"

        self.assertEqual(detect_id_side(text), "back")
        self.assertGreater(_side_scores(text)["back"], _side_scores(text)["front"])

    def test_weak_or_partial_text_does_not_force_side(self):
        self.assertEqual(detect_id_side("中華民國"), "unknown")
        self.assertEqual(detect_id_side("模糊照片 12345"), "unknown")

    @patch("sales.services.id_ocr.recognize_side")
    @patch("sales.services.id_ocr._vision_client")
    def test_rejects_swapped_front_and_back(self, _vision_client, recognize_side):
        recognize_side.side_effect = (
            SimpleNamespace(text="住址 台北市中山區\n0040750525"),
            SimpleNamespace(text="中華民國國民身分證\n姓名 林小華\nA123456789"),
        )

        with self.assertRaisesRegex(IdOcrError, "正反面似乎放反"):
            recognize_id_card(b"front", b"back")

    @patch("sales.services.id_ocr.recognize_side")
    @patch("sales.services.id_ocr._vision_client")
    def test_rejects_two_front_images(self, _vision_client, recognize_side):
        front_result = SimpleNamespace(
            text="中華民國國民身分證\n姓名 林小華\nA123456789"
        )
        recognize_side.side_effect = (front_result, front_result)

        with self.assertRaisesRegex(IdOcrError, "都是證件正面"):
            recognize_id_card(b"front", b"back")

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

    def test_preserves_chinese_ten_floor_in_address(self):
        text = "桃園市八德區大安里2鄰\n住址\n和平路649巷13號十樓"

        result = extract_fields(text, "back")

        self.assertEqual(
            result["address"], "桃園市八德區大安里2鄰和平路649巷13號十樓"
        )

    def test_taiwan_id_checksum(self):
        self.assertTrue(validate_taiwan_id("A123456789"))
        self.assertFalse(validate_taiwan_id("A123456788"))
        self.assertFalse(validate_taiwan_id("NOT-AN-ID"))

    def test_detects_resident_certificate_front_and_back(self):
        front = (
            "中華民國居留證\nR.O.C.(Taiwan) Resident Certificate\n"
            "外僑居留證 Alien Resident Certificate\n出生日期 Date of birth\n"
            "居留地址 Residence address"
        )
        back = (
            "National Immigration Agency\n持證人可多次入出國\n"
            "I<TWNX000000000000000000000<<<<<<<<<<<"
        )

        self.assertEqual(detect_resident_certificate_side(front), "front")
        self.assertEqual(detect_resident_certificate_side(back), "back")
        self.assertGreater(
            _resident_side_scores(front)["front"],
            _resident_side_scores(front)["back"],
        )

    def test_extracts_resident_certificate_front_fields(self):
        text = (
            "中華民國居留證\n外僑居留證(ARC)\n"
            "類別 Type\n核發單位 Authority\n新北市服務站\n"
            "證號 UI No.\n王小美\nF900000001\n姓名 Name\nWANG XIAO MEI\n"
            "出生日期 Date of birth\n2001/02/03\n"
            "居留期限 Date of expiry\n2028/09/07\n"
            "居留地址 Residence address\n2696648330\n"
            "新北市汐止區測試路83巷3號612房\n"
        )

        result = extract_resident_certificate_fields(text)

        self.assertEqual(result["name"], "王小美")
        self.assertEqual(result["birth_date"], "2001-02-03")
        self.assertEqual(result["id_number"], "F900000001")
        self.assertEqual(result["address"], "新北市汐止區測試路83巷3號612房")

    def test_repairs_resident_id_digit_confusion(self):
        result = extract_resident_certificate_fields(
            "中華民國居留證\n證號 UI No. F9OOO00001\nMULTIPLE RE-ENTRY"
        )

        self.assertEqual(result["id_number"], "F900000001")

    def test_resident_layout_name_wins_over_residence_purpose(self):
        def annotation(text, left, top, right, bottom):
            vertices = [
                SimpleNamespace(x=left, y=top),
                SimpleNamespace(x=right, y=top),
                SimpleNamespace(x=right, y=bottom),
                SimpleNamespace(x=left, y=bottom),
            ]
            return SimpleNamespace(
                description=text,
                bounding_poly=SimpleNamespace(vertices=vertices),
            )

        front = SimpleNamespace(
            image=SimpleNamespace(width=1200, height=800),
            annotations=(
                annotation("F900000001", 80, 280, 270, 315),
                annotation("王小美", 290, 282, 410, 318),
                annotation("就學", 480, 500, 550, 535),
            ),
        )

        self.assertEqual(_extract_resident_name_from_layout(front), "王小美")

    @patch("sales.services.id_ocr.recognize_resident_certificate_side")
    @patch("sales.services.id_ocr._vision_client")
    def test_rejects_swapped_resident_certificate_sides(
        self, _vision_client, recognize_side
    ):
        recognize_side.side_effect = (
            SimpleNamespace(
                text="I<TWNX000000000<<<<<<<<<<", angle=0
            ),
            SimpleNamespace(
                text="中華民國居留證 Resident Certificate", angle=0
            ),
        )

        with self.assertRaisesRegex(IdOcrError, "正反面似乎放反"):
            recognize_id_card(
                b"front", b"back", document_type="resident_certificate"
            )


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
        self.assertEqual(
            IdOcrJob.objects.get().document_type,
            IdOcrJob.DocumentType.NATIONAL_ID,
        )
        queue.enqueue.assert_called_once()

    @patch("sales.views.django_rq.get_queue")
    def test_queues_resident_certificate_ocr(self, get_queue):
        queue = get_queue.return_value
        queue.count = 0
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("id_card_ocr"),
            {
                "front": self.image("front.png"),
                "back": self.image("back.png"),
                "document_type": "resident_certificate",
            },
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["document_type"], "resident_certificate")
        self.assertEqual(
            IdOcrJob.objects.get().document_type,
            IdOcrJob.DocumentType.RESIDENT_CERTIFICATE,
        )

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

    @patch("sales.jobs.recognize_id_card")
    def test_worker_routes_resident_certificate_job(self, recognize):
        recognize.return_value = {"fields": {}, "warnings": [], "rotation": {}}
        job = IdOcrJob.objects.create(
            created_by=self.user,
            front=self.image("front.png"),
            back=self.image("back.png"),
            document_type=IdOcrJob.DocumentType.RESIDENT_CERTIFICATE,
            photo_token="resident-v1",
        )

        run_id_ocr_job(str(job.pk))

        recognize.assert_called_once()
        self.assertEqual(
            recognize.call_args.kwargs["document_type"],
            IdOcrJob.DocumentType.RESIDENT_CERTIFICATE,
        )

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
