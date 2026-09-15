import io
import tempfile

from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from sales.models import VehicleModel, VehicleColor, VehicleCatalogEntry, UserAccountAuditLog


class CatalogColorListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = get_user_model().objects.create_superuser("admin", password="Catalog-color-test-83!")
        cls.model = VehicleModel.objects.create(
            brand="SUZUKI", name="SUI 125", model_number="UQ125DA", model_year=2026,
            model_code=VehicleModel.ModelType.FRONT_DISC_REAR_DRUM, energy_type="gas",
        )
        cls.gray = VehicleColor.objects.create(vehicle_model=cls.model, name="灰")
        cls.white = VehicleColor.objects.create(vehicle_model=cls.model, name="白")
        cls.inactive = VehicleColor.objects.create(vehicle_model=cls.model, name="停用黃", active=False)
        cls.entry = VehicleCatalogEntry.objects.create(vehicle_model=cls.model, published=True)

    def image(self):
        data = io.BytesIO()
        Image.new("RGB", (12, 12), "gray").save(data, "PNG")
        return SimpleUploadedFile("gray.png", data.getvalue(), content_type="image/png")

    def test_list_shows_colors_without_photos_and_separate_counts(self):
        # 只有車款主圖不能被誤用到所有車色。
        self.entry.image = "catalog/already-public.png"
        self.entry.save()
        response = self.client.get(reverse("catalog"))
        self.assertContains(response, "共 1 款車型／2 個車色選項")
        self.assertContains(response, "2026/UQ125DA/前碟後鼓/灰")
        self.assertContains(response, "2026/UQ125DA/前碟後鼓/白")
        self.assertContains(response, "此車色圖片待補", count=2)
        self.assertNotContains(response, "停用黃")
        self.assertNotContains(response, f'src="{reverse("catalog_image", args=[self.model.pk])}"')
        self.assertContains(response, f'?color={self.gray.pk}')

    def test_pagination_and_filters_operate_on_color_options(self):
        for index in range(12):
            VehicleColor.objects.create(vehicle_model=self.model, name=f"其他色{index:02d}")
        first = self.client.get(reverse("catalog"), {"model": self.model.pk})
        second = self.client.get(reverse("catalog"), {"model": self.model.pk, "page": 2})
        self.assertEqual(first.context["page_obj"].paginator.count, 14)
        self.assertEqual(len(first.context["cards"]), 12)
        self.assertEqual(len(second.context["cards"]), 2)
        first_ids = {c["color"].pk for c in first.context["cards"]}
        self.assertFalse(first_ids & {c["color"].pk for c in second.context["cards"]})
        self.assertEqual(self.client.get(reverse("catalog"), {"energy": "electric"}).context["page_obj"].paginator.count, 0)
        self.entry.published = False
        self.entry.save()
        self.assertEqual(self.client.get(reverse("catalog")).context["page_obj"].paginator.count, 0)

    def test_selected_color_is_validated_against_active_model_colors(self):
        other = VehicleModel.objects.create(brand="TEST", name="另一款", energy_type="gas")
        foreign = VehicleColor.objects.create(vehicle_model=other, name="外款藍")
        url = reverse("catalog_detail", args=[self.model.pk])
        for invalid in [self.inactive.pk, foreign.pk, "bad", "9" * 100, ""]:
            self.assertIsNone(self.client.get(url, {"color": invalid}).context["selected_color_id"])
        response = self.client.get(url, {"color": self.gray.pk})
        self.assertEqual(response.context["selected_color_id"], self.gray.pk)
        self.assertContains(response, f'value="{self.gray.pk}" required aria-label="灰" checked')

    def test_main_image_assignment_is_explicit_audited_and_repeatable(self):
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            self.entry.image.save("main.png", self.image())
            self.client.force_login(self.root)
            url = reverse("catalog_edit", args=[self.model.pk])
            for revision in (0, 1):
                response = self.client.post(url, {"expected_revision": revision, "position": 0,
                    "published": "on", "main_image_color": self.gray.pk})
                self.assertEqual(response.status_code, 302)
            self.gray.refresh_from_db()
            self.white.refresh_from_db()
            self.assertEqual(self.gray.catalog_image.name, self.entry.image.name)
            self.assertFalse(self.white.catalog_image)
            audit = UserAccountAuditLog.objects.order_by("-pk").first()
            self.assertEqual(audit.metadata["main_image_color_id"], self.gray.pk)
            self.assertContains(self.client.get(reverse("catalog")),
                f'src="{reverse("catalog_color_image", args=[self.model.pk, self.gray.pk])}"', count=1)
            stale = self.client.post(url, {"expected_revision": 0, "position": 0,
                "published": "on", "main_image_color": self.white.pk})
            self.assertContains(stale, "車款展示已被其他視窗更新")
            self.white.refresh_from_db()
            self.assertFalse(self.white.catalog_image)

    def test_main_image_assignment_rejects_missing_image_and_overwrite(self):
        self.client.force_login(self.root)
        url = reverse("catalog_edit", args=[self.model.pk])
        payload = {"expected_revision": 0, "position": 0, "published": "on", "main_image_color": self.gray.pk}
        self.assertContains(self.client.post(url, payload), "請先儲存主圖")
        self.entry.image = "catalog/main.png"
        self.entry.save()
        self.gray.catalog_image = "catalog/different.png"
        self.gray.save()
        self.assertContains(self.client.post(url, payload), "此車色已有不同圖片")
        self.gray.refresh_from_db()
        self.assertEqual(self.gray.catalog_image.name, "catalog/different.png")
        response = self.client.post(url, {**payload, "main_image_color": self.inactive.pk})
        self.assertIn("main_image_color", response.context["form"].errors)
        normal_user = get_user_model().objects.create_user("no-catalog-admin")
        self.client.force_login(normal_user)
        self.assertEqual(self.client.post(url, payload).status_code, 403)

    def test_enabled_names_are_separate_for_each_year(self):
        previous = VehicleModel.objects.create(
            brand="SUZUKI", name="SUI 125", model_number="UQ125DA", model_year=2025,
            model_code=VehicleModel.ModelType.FRONT_DISC_REAR_DRUM, energy_type="gas",
        )
        VehicleColor.objects.create(vehicle_model=previous, name="2025限定紅")
        self.client.force_login(self.root)
        response = self.client.get(reverse("vehicle_model_list"), {"q": "SUI"})
        versions = {m.pk: m for g in response.context["vehicle_model_groups"] for f in g["families"] for m in f["models"]}
        self.assertEqual({c.name for c in versions[self.model.pk].enabled_colors}, {"灰", "白"})
        self.assertEqual([c.name for c in versions[previous.pk].enabled_colors], ["2025限定紅"])
        self.assertContains(response, "2025限定紅")
        self.assertContains(response, '<li>灰</li>', html=True)
        self.assertNotContains(response, "停用黃")

    def test_zero_active_colors_is_explicit(self):
        self.model.colors.update(active=False)
        self.assertContains(self.client.get(reverse("catalog")), "目前沒有符合條件的啟用車色")
        self.client.force_login(self.root)
        self.assertContains(self.client.get(reverse("vehicle_model_list")), "尚無啟用顏色")
