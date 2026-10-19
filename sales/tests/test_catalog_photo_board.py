import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from sales.models import UserAccountAuditLog, VehicleCatalogEntry, VehicleColor, VehicleModel
from sales.services.remote_image import ContentFile, RemoteImageError
from sales.tests import test_catalog_color_list as color_fixtures
from sales.tests.test_catalog_remote_image import image_bytes

URL = "https://www.e-moving.com.tw/emwspublished/C0013/28_20240712163321.jpg"


class CatalogPhotoBoardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        color_fixtures.CatalogColorListTests.setUpTestData.__func__(cls)
        cls.staff = get_user_model().objects.create_user("staff", password="Photo-board-test-91!")
        cls.ez1 = VehicleModel.objects.create(brand="e-moving", name="EZ1", model_number="EZ1", model_year=2021,
                                              energy_type="light_electric")
        cls.blue = VehicleColor.objects.create(vehicle_model=cls.ez1, name="神秘霧藍", catalog_image="catalog/colors/blue.png")
        cls.mango = VehicleColor.objects.create(vehicle_model=cls.ez1, name="芒果雪酪")
        cls.stopped = VehicleModel.objects.create(brand="SUZUKI", name="停用車", model_number="STOP", energy_type="gas",
                                                  active=False)
        VehicleColor.objects.create(vehicle_model=cls.stopped, name="停用車的色")

    image = color_fixtures.CatalogColorListTests.image

    def setUp(self):
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        settings = override_settings(MEDIA_ROOT=media.name)
        settings.enable()
        self.addCleanup(settings.disable)
        cache.clear()
        self.client.force_login(self.root)
        self.board = reverse("catalog_photo_board")

    def save(self, color, **data):
        data.setdefault("expected", color.catalog_image.name)
        return self.client.post(reverse("catalog_photo_save", args=[color.pk]), data)

    def test_board_lists_active_colors_with_counts_and_filters(self):
        response = self.client.get(self.board)
        self.assertEqual((response.context["missing_count"], response.context["total_count"]), (3, 4))
        self.assertContains(response, "缺圖 <b data-photo-missing>3</b> 張／共 <b data-photo-total>4</b> 張", html=False)
        self.assertContains(response, "芒果雪酪")
        self.assertNotContains(response, "停用黃")
        self.assertNotContains(response, "停用車的色")
        self.assertContains(response, 'data-has-photo="1"', count=1)
        self.assertContains(response, reverse("catalog_photo_thumb", args=[self.blue.pk]) + "?v=blue.png")
        self.assertNotContains(response, "data-missing-only")
        self.assertContains(self.client.get(self.board, {"missing": "1"}), "data-missing-only")
        found = self.client.get(self.board, {"q": "霧藍"})
        self.assertEqual(found.context["total_count"], 2)
        self.assertNotContains(found, "SUI 125")
        self.assertContains(self.client.get(self.board, {"q": "沒有這台"}), "找不到符合")

    def test_only_root_can_view_or_save(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.board).status_code, 403)
        self.assertEqual(self.save(self.mango, image=self.image()).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.board).status_code, 302)
        self.mango.refresh_from_db()
        self.assertFalse(self.mango.catalog_image)

    def test_upload_saves_in_place_and_audits(self):
        VehicleCatalogEntry.objects.filter(vehicle_model=self.ez1).delete()
        response = self.save(self.mango, image=self.image())
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.mango.refresh_from_db()
        self.assertTrue(data["ok"])
        self.assertFalse(data["replaced"])
        self.assertEqual(data["image"], self.mango.catalog_image.name)
        self.assertRegex(self.mango.catalog_image.name, r"catalog/colors/\d{4}/\d{2}/[0-9a-f]{32}\.png$")
        self.assertTrue(VehicleCatalogEntry.objects.get(vehicle_model=self.ez1).published)
        audit = UserAccountAuditLog.objects.latest("pk")
        self.assertEqual((audit.metadata["color_id"], audit.metadata["source"], audit.metadata["page"]),
                         (self.mango.pk, "upload", "photo_board"))
        thumb = self.client.get(data["thumb"])
        self.assertEqual((thumb.status_code, thumb["Content-Type"]), (200, "image/webp"))
        self.assertIn("immutable", thumb["Cache-Control"])
        page = self.client.get(reverse("catalog_detail", args=[self.ez1.pk]), {"color": self.mango.pk})
        self.assertContains(page, reverse("catalog_color_image", args=[self.ez1.pk, self.mango.pk]))

    def test_link_uses_safe_download_and_reports_failures_per_cell(self):
        with patch("sales.catalog_photo_views.fetch_image",
                   return_value=ContentFile(image_bytes(), "b" * 32 + ".jpg")) as fetch:
            response = self.save(self.mango, url=f" {URL} ")
        fetch.assert_called_once_with(URL)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(UserAccountAuditLog.objects.latest("pk").metadata["url"], URL)
        with patch("sales.catalog_photo_views.fetch_image",
                   side_effect=RemoteImageError("這個連結指向內部網路或保留位址，基於安全不能下載。")):
            response = self.save(self.gray, url="http://10.0.0.1/a.jpg")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"ok": False, "error": "這個連結指向內部網路或保留位址，基於安全不能下載。"})
        with patch("sales.catalog_photo_views.fetch_image") as fetch:
            self.assertIn("http", self.save(self.gray, url="file:///etc/passwd").json()["error"])
        fetch.assert_not_called()
        self.gray.refresh_from_db()
        self.assertFalse(self.gray.catalog_image)

    def test_invalid_input_is_rejected_without_change(self):
        fake = SimpleUploadedFile("fake.png", b"<svg></svg>", content_type="image/png")
        for data in ({"image": fake}, {}, {"image": self.image(), "url": URL}):
            response = self.save(self.mango, **data)
            self.assertEqual(response.status_code, 400, data)
            self.assertFalse(response.json()["ok"])
        self.assertEqual(self.client.get(reverse("catalog_photo_save", args=[self.mango.pk])).status_code, 405)
        self.mango.refresh_from_db()
        self.assertFalse(self.mango.catalog_image)

    def test_replace_requires_current_image_and_records_previous(self):
        stale = self.save(self.blue, image=self.image(), expected="")
        self.assertEqual(stale.status_code, 409)
        self.assertIn("重新整理", stale.json()["error"])
        response = self.save(self.blue, image=self.image())
        self.assertTrue(response.json()["replaced"])
        self.assertEqual(UserAccountAuditLog.objects.latest("pk").metadata["previous_image"], "catalog/colors/blue.png")

    def test_inactive_color_or_model_cannot_be_saved(self):
        self.mango.active = False
        self.mango.save()
        self.assertEqual(self.save(self.mango, image=self.image()).status_code, 409)
        self.assertEqual(self.client.get(reverse("catalog_photo_thumb", args=[self.blue.pk])).status_code, 404)  # 檔案不存在
        self.ez1.active = False
        self.ez1.save()
        self.assertEqual(self.save(self.blue, image=self.image()).status_code, 409)
        self.assertEqual(self.client.get(reverse("catalog_photo_thumb", args=[self.mango.pk])).status_code, 404)

    def test_data_maintenance_entry_shows_missing_count(self):
        response = self.client.get(reverse("data_maintenance"))
        self.assertContains(response, reverse("catalog_photo_board") + "?missing=1")
        self.assertContains(response, "缺圖 3 張")
        self.client.force_login(self.staff)
        self.assertNotContains(self.client.get(reverse("data_maintenance")), "車色圖片")

    def test_model_list_marks_missing_colors_and_filters(self):
        url = reverse("vehicle_model_list")
        html = self.client.get(url).content.decode()
        self.assertIn('<span class="is-missing-photo">芒果雪酪</span>', html)
        self.assertIn("<span>神秘霧藍、</span>", html)
        self.assertIn('<em class="color-peek__missing">缺圖 1</em>', html)
        self.assertIn('<p class="color-peek__missing-list"><strong>缺圖</strong><span>芒果雪酪</span></p>', html)
        self.assertIn(f'{self.board}?missing=1#model-{self.ez1.pk}', html)
        self.assertIn(f'href="{self.board}?missing=1"', html)
        self.assertIn("缺圖 <b>3</b> 張", html)
        searched = self.client.get(url, {"q": "EZ1"}).content.decode()
        self.assertIn(f'href="{self.board}?missing=1&amp;q=EZ1"', searched)
        self.blue.catalog_image = ""
        self.blue.save()
        self.mango.catalog_image = "catalog/colors/mango.png"
        self.mango.save()
        VehicleColor.objects.filter(vehicle_model=self.model).update(catalog_image="catalog/colors/x.png")
        filtered = self.client.get(url, {"missing_photo": "1"})
        self.assertTrue(filtered.context["selected"]["missing_photo"])
        self.assertContains(filtered, "EZ1")
        self.assertNotContains(filtered, "SUI 125")
        self.client.force_login(self.staff)
        staff_page = self.client.get(url)
        if staff_page.status_code == 200:
            self.assertNotContains(staff_page, self.board)
