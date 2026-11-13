"""T-163：通路類別不再由使用者設定，系統依來源類型自動帶入。"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import SalesSource, SalesSourceCategory


class SourceCategoryAutoAssignTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            "t163-root", password="test-only"
        )
        self.client.force_login(self.user)

    def test_platform_create_needs_no_category(self):
        response = self.client.post(
            reverse("sales_source_create") + "?kind=platform",
            {
                "name": "T163 平台",
                "active": "on",
                "policies-TOTAL_FORMS": "0",
                "policies-INITIAL_FORMS": "0",
                "policies-MIN_NUM_FORMS": "0",
                "policies-MAX_NUM_FORMS": "1000",
                "platform_contacts-TOTAL_FORMS": "0",
                "platform_contacts-INITIAL_FORMS": "0",
                "platform_contacts-MIN_NUM_FORMS": "0",
                "platform_contacts-MAX_NUM_FORMS": "1000",
            },
        )

        self.assertRedirects(response, reverse("sales_source_platform_list"))
        source = SalesSource.objects.get(name="T163 平台")
        self.assertEqual(source.source_type, SalesSource.SourceType.PLATFORM)
        self.assertEqual(source.category.name, "網路平台")

    def test_platform_form_has_no_category_field(self):
        response = self.client.get(reverse("sales_source_create"), {"kind": "platform"})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("category", response.context["form"].fields)
        self.assertNotContains(response, 'name="category"')

    def test_model_assigns_default_category_by_source_type(self):
        dealer = SalesSource.objects.create(
            name="T163 車行", source_type=SalesSource.SourceType.DEALER
        )
        staff = SalesSource.objects.create(
            name="T163 人員", source_type=SalesSource.SourceType.STORE
        )

        self.assertEqual(dealer.category.name, "車行")
        self.assertEqual(staff.category.name, "本店員工")

    def test_existing_store_subcategory_is_kept_on_edit(self):
        yusheng = SalesSourceCategory.objects.get(name="馭盛")
        source = SalesSource.objects.create(
            name="展場",
            source_type=SalesSource.SourceType.STORE,
            category=yusheng,
        )

        response = self.client.post(
            reverse("sales_source_edit", args=[source.pk]),
            {"name": "展場", "phone": "", "staff_commission": "0", "active": "on"},
        )

        self.assertRedirects(response, reverse("sales_source_staff_list"))
        source.refresh_from_db()
        self.assertEqual(source.category, yusheng)

    def test_mismatched_category_follows_source_type(self):
        platform_category = SalesSourceCategory.objects.get(name="網路平台")
        source = SalesSource.objects.create(
            name="T163 錯類別車行",
            source_type=SalesSource.SourceType.DEALER,
            category=platform_category,
        )

        self.assertEqual(source.source_type, SalesSource.SourceType.DEALER)
        self.assertEqual(source.category.system_behavior, SalesSource.SourceType.DEALER)

    def test_default_category_is_created_when_missing(self):
        SalesSource.objects.filter(source_type=SalesSource.SourceType.PLATFORM).delete()
        SalesSourceCategory.objects.filter(
            system_behavior=SalesSource.SourceType.PLATFORM
        ).delete()

        source = SalesSource.objects.create(
            name="T163 新平台", source_type=SalesSource.SourceType.PLATFORM
        )

        self.assertEqual(source.category.name, "網路平台")
        self.assertEqual(
            source.category.system_behavior, SalesSource.SourceType.PLATFORM
        )

    def test_inactive_default_category_still_allows_create(self):
        SalesSourceCategory.objects.filter(
            system_behavior=SalesSource.SourceType.DEALER
        ).update(active=False)

        source = SalesSource.objects.create(
            name="T163 停用類別車行", source_type=SalesSource.SourceType.DEALER
        )

        self.assertEqual(source.category.name, "車行")

    def test_category_screen_is_removed(self):
        maintenance = self.client.get(reverse("data_maintenance"))
        old_url = self.client.get("/data/channels/categories/")

        self.assertEqual(maintenance.status_code, 200)
        self.assertNotContains(maintenance, "通路類別")
        self.assertRedirects(old_url, reverse("data_maintenance"))
