import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from sales.catalog_views import CatalogForm
from sales.models import VehicleColor, VehicleModel, VehicleCatalogEntry, UserAccountAuditLog
from sales.tests import test_catalog_color_list as color_fixtures


class CatalogManagementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        color_fixtures.CatalogColorListTests.setUpTestData.__func__(cls)
        cls.other = VehicleModel.objects.create(brand="OTHER", name="另一車型", model_number="OTHER125", energy_type="gas")
        cls.disabled = VehicleModel.objects.create(brand="停用品牌", name="停用車型", model_number="STOP125", energy_type="gas", active=False)

    image = color_fixtures.CatalogColorListTests.image

    def setUp(self):
        self.client.force_login(self.root)
        self.url = reverse("catalog_edit", args=[self.model.pk])
        self.payload = {"expected_revision": 0, "description": "更新介紹", "position": 0}

    def test_manage_hides_disabled_but_retains_unpublished(self):
        response = self.client.get(reverse("catalog_manage"))
        self.assertEqual(response.context["page_obj"].paginator.count, 2)
        self.assertContains(response, "另一車型")
        self.assertContains(response, "未上架")
        self.assertNotContains(response, "停用品牌")
        self.assertNotContains(response, "STOP125")
        for method in (self.client.get, self.client.post):
            self.assertEqual(method(reverse("catalog_edit", args=[self.disabled.pk]), self.payload).status_code, 404)
        self.assertFalse(VehicleCatalogEntry.objects.filter(vehicle_model=self.disabled).exists())

    def test_filters_intersect_options_and_keep_pagination(self):
        for year in range(2000, 2022):
            VehicleModel.objects.create(brand="SUZUKI", name="SUI 125", model_number="UQ125DA", model_year=year, energy_type="gas")
        filters = {"brand": "SUZUKI", "model_name": "SUI 125", "model_number": "UQ125DA", "q": "SUI", "page": 2}
        response = self.client.get(reverse("catalog_manage"), filters)
        self.assertEqual(response.context["page_obj"].paginator.count, 23)
        self.assertEqual(len(response.context["page_obj"]), 3)
        self.assertEqual(response.context["model_names"], ["SUI 125"])
        self.assertEqual(response.context["model_numbers"], ["UQ125DA"])
        self.assertContains(response, "brand=SUZUKI&amp;model_name=SUI+125&amp;model_number=UQ125DA&amp;q=SUI&amp;page=1")
        for key, value in (("brand", "OTHER"), ("model_name", "另一車型"), ("model_number", "OTHER125"), ("q", "不匹配")):
            self.assertEqual(self.client.get(reverse("catalog_manage"), {**filters, key: value}).context["page_obj"].paginator.count, 0)

    def test_only_active_color_fields_and_preserve_disabled_photo(self):
        self.inactive.catalog_image = "catalog/keep-original.png"
        self.inactive.save()
        response = self.client.get(self.url)
        self.assertNotContains(response, "停用黃")
        self.assertEqual(len(response.context["form"].color_sections), 2)
        self.assertNotIn(f"color_image_{self.inactive.pk}", response.context["form"].fields)
        self.assertEqual(self.client.post(self.url, self.payload).status_code, 302)
        self.inactive.refresh_from_db()
        self.assertEqual(self.inactive.catalog_image.name, "catalog/keep-original.png")

    def test_inactive_foreign_and_unknown_color_posts_rejected(self):
        foreign = VehicleColor.objects.create(vehicle_model=self.other, name="其他紅")
        for pk in (self.inactive.pk, foreign.pk, 999999):
            response = self.client.post(self.url, {**self.payload, f"color_remove_{pk}": "on"})
            self.assertContains(response, "車色已停用或不屬於此車款")
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.revision, 0)
        self.assertFalse(UserAccountAuditLog.objects.exists())

    def test_zero_active_colors_and_upload_remove_conflict(self):
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            response = self.client.post(self.url, {**self.payload, f"color_image_{self.gray.pk}": self.image(), f"color_remove_{self.gray.pk}": "on"})
            self.assertContains(response, "同一車色不可同時上傳與移除圖片")
        self.model.colors.update(active=False)
        self.assertContains(self.client.get(self.url), "目前沒有啟用車色")

    def test_state_changes_after_validation_block_whole_save(self):
        original_clean = CatalogForm.clean
        for target, field, value in ((self.model, "active", False), (self.gray, "active", False), (self.gray, "catalog_image", "catalog/another.png")):
            def changed_during_validation(form):
                data = original_clean(form)
                type(target).objects.filter(pk=target.pk).update(**{field: value})
                return data
            with patch.object(CatalogForm, "clean", changed_during_validation):
                response = self.client.post(self.url, self.payload)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].non_field_errors())
            self.entry.refresh_from_db()
            self.assertEqual(self.entry.revision, 0)
            self.assertNotEqual(self.entry.description, "更新介紹")
            type(target).objects.filter(pk=target.pk).update(**{field: True if field == "active" else ""})
        self.assertFalse(UserAccountAuditLog.objects.exists())

    def test_private_preview_does_not_publish_and_rejects_other_accounts(self):
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            self.entry.published = False
            self.entry.image.save("main.png", self.image())
            self.gray.catalog_image.save("gray.png", self.image())
            routes = [("catalog_preview_image", [self.model.pk]), ("catalog_preview_color_image", [self.model.pk, self.gray.pk])]
            for name, args in routes:
                response = self.client.get(reverse(name, args=args))
                try:
                    self.assertEqual(response.status_code, 200)
                    self.assertIn("private", response["Cache-Control"])
                    self.assertIn("no-store", response["Cache-Control"])
                finally:
                    # 由測試客戶端的串流 wrapper 關閉回應；直接 close 會發出
                    # request_finished，誤關 PostgreSQL TestCase 的交易連線。
                    b"".join(response.streaming_content)
            self.assertEqual(self.client.get(reverse("catalog_image", args=[self.model.pk])).status_code, 404)
            self.assertEqual(self.client.get(reverse("catalog_color_image", args=[self.model.pk, self.gray.pk])).status_code, 404)
            user = get_user_model().objects.create_user("preview-denied")
            self.client.force_login(user)
            for name, args in routes:
                self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 403)
            self.client.logout()
            for name, args in routes:
                self.assertIn(self.client.get(reverse(name, args=args)).status_code, (302, 403))

    def test_preview_rejects_inactive_or_foreign_colors_and_missing_files(self):
        foreign = VehicleColor.objects.create(vehicle_model=self.other, name="其他紅")
        for pk in (self.inactive.pk, foreign.pk, self.gray.pk):
            self.assertEqual(self.client.get(reverse("catalog_preview_color_image", args=[self.model.pk, pk])).status_code, 404)
        self.gray.catalog_image = "catalog/absent.png"
        self.gray.save()
        self.assertEqual(self.client.get(reverse("catalog_preview_color_image", args=[self.model.pk, self.gray.pk])).status_code, 404)

    def test_active_color_upload_is_saved_and_audited(self):
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            self.assertEqual(self.client.post(self.url, {**self.payload, f"color_image_{self.gray.pk}": self.image()}).status_code, 302)
            self.gray.refresh_from_db()
            self.assertTrue(self.gray.catalog_image)
            self.assertTrue(UserAccountAuditLog.objects.filter(metadata__model_id=self.model.pk).exists())
